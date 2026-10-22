"""The TUI's A2A client port (R20.2): the SDK client over JSON-RPC with streaming and
``A2A-Version: 1.0``, plus a scripted client for tests and snapshots.

issue-25: ``complete`` sends the same control envelope any A2A client can (R5.1), and
``commands`` reads the card's commands extension for ``/`` completion (R6.7).

issue-38: ``send`` takes the message's parts (text and ``raw`` file parts) and the speaker
setting (``speak``); ``media`` reads the card's media extension; ``get_media`` streams a
medium of the task from the agent's own media route with the participant header."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.client.client import Client as A2AClient
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Part,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.types import Role as A2ARole
from a2a.utils.errors import TaskNotFoundError
from google.protobuf import json_format, struct_pb2
from pydantic import ValidationError

from tiny_harness.harness.agents import A2AEvent, unwrap
from tiny_harness.harness.commands import COMMANDS_EXT_URI, CommandsExtensionParams, CommandSpec
from tiny_harness.harness.media.extension import MEDIA_EXT_URI, MediaExtensionParams
from tiny_harness.interaction.a2ui import A2UI_MEDIA_TYPE, Action
from tiny_harness.service.inbox import complete_message

type EventSource = AsyncIterator[A2AEvent]


type MediaSource = AsyncIterator[bytes]


@dataclass(frozen=True)
class Attachment:
    """A local file the user attached (or recorded) for the next message: its bytes, the
    type its signature names, and what the surface shows on its chip."""

    name: str
    media_type: str
    data: bytes
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    voice: bool = False

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def kind(self) -> str:
        return self.media_type.split("/", 1)[0]


class A2AClientPort(Protocol):
    def send(
        self, parts: Sequence[Part], *, task_id: str | None, context_id: str, speak: bool = False
    ) -> EventSource: ...

    def send_action(self, action: Action, *, task_id: str, context_id: str) -> EventSource: ...

    def subscribe(self, task_id: str) -> EventSource: ...

    async def cancel(self, task_id: str) -> Task: ...

    def complete(self, task_id: str) -> EventSource: ...

    async def get_task(self, task_id: str) -> Task: ...

    def commands(self) -> tuple[CommandSpec, ...]: ...

    def media(self) -> MediaExtensionParams | None: ...

    def get_media(self, url: str) -> MediaSource: ...

    async def close(self) -> None: ...


def card_commands(card: AgentCard) -> tuple[CommandSpec, ...]:
    """The commands the card's commands extension lists; none when it is absent or its
    params do not parse (the extension is optional, R6.7)."""
    for extension in card.capabilities.extensions:
        if extension.uri == COMMANDS_EXT_URI:
            try:
                params = CommandsExtensionParams.model_validate(
                    json_format.MessageToDict(extension.params)
                )
            except ValidationError:
                return ()
            return params.commands
    return ()


def card_media(card: AgentCard) -> MediaExtensionParams | None:
    """The card's media extension params; ``None`` when the agent takes no media or the
    params do not parse."""
    for extension in card.capabilities.extensions:
        if extension.uri == MEDIA_EXT_URI:
            try:
                return MediaExtensionParams.model_validate(
                    json_format.MessageToDict(extension.params)
                )
            except ValidationError:
                return None
    return None


def file_part(attachment: Attachment) -> Part:
    """A ``raw`` file part; a recording says so (``voice``, ``durationMs``)."""
    part = Part(raw=attachment.data, media_type=attachment.media_type, filename=attachment.name)
    if attachment.voice:
        part.metadata.update({"voice": True})
    if attachment.voice and attachment.duration_ms is not None:
        part.metadata.update({"durationMs": attachment.duration_ms})
    return part


def user_parts(text: str, files: Sequence[Attachment] = ()) -> list[Part]:
    """The parts of a user message: its text (when there is any), then each file."""
    parts = [Part(text=text)] if text or not files else []
    parts.extend(file_part(f) for f in files)
    return parts


def parts_message(
    parts: Sequence[Part],
    *,
    task_id: str | None,
    context_id: str,
    participant: str | None,
    speak: bool = False,
) -> Message:
    message = Message(
        message_id=uuid.uuid4().hex,
        context_id=context_id,
        role=A2ARole.ROLE_USER,
        parts=list(parts),
    )
    if task_id:
        message.task_id = task_id
    if participant:
        message.metadata.update({"participant_id": participant})
    if speak:
        message.metadata.update({"speak": True})
    return message


def user_message(
    text: str,
    *,
    files: Sequence[Attachment] = (),
    task_id: str | None,
    context_id: str,
    participant: str | None,
    speak: bool = False,
) -> Message:
    return parts_message(
        user_parts(text, files),
        task_id=task_id,
        context_id=context_id,
        participant=participant,
        speak=speak,
    )


def text_of(parts: Sequence[Part]) -> str:
    return "\n".join(p.text for p in parts if p.HasField("text"))


def action_message(
    action: Action, *, task_id: str, context_id: str, participant: str | None
) -> Message:
    value = struct_pb2.Value()
    value.struct_value.update(action.payload())
    message = Message(
        message_id=uuid.uuid4().hex,
        context_id=context_id,
        task_id=task_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(data=value, media_type=A2UI_MEDIA_TYPE)],
    )
    if participant:
        message.metadata.update({"participant_id": participant})
    return message


class SdkClient:
    """``a2a-sdk`` over JSON-RPC with streaming; the card is resolved from the base URL."""

    def __init__(
        self,
        client: A2AClient,
        *,
        http: httpx.AsyncClient,
        participant: str | None,
        card: AgentCard | None = None,
        base_url: str = "",
    ) -> None:
        self._client = client
        self._http = http
        self.participant = participant
        self.card = card
        self.base_url = base_url  # media is fetched from this origin only

    @classmethod
    async def connect(cls, url: str, *, participant: str | None = None) -> SdkClient:
        http = httpx.AsyncClient(timeout=httpx.Timeout(60, read=None))
        if participant:
            http.headers["X-Participant-Id"] = participant
        card = await A2ACardResolver(http, url).get_agent_card()
        client = await create_client(
            card,
            client_config=ClientConfig(
                httpx_client=http, streaming=True, supported_protocol_bindings=["JSONRPC"]
            ),
        )
        return cls(client, http=http, participant=participant, card=card, base_url=url)

    async def _stream(self, message: Message) -> EventSource:
        async for response in self._client.send_message(SendMessageRequest(message=message)):
            yield unwrap(response)

    def send(
        self, parts: Sequence[Part], *, task_id: str | None, context_id: str, speak: bool = False
    ) -> EventSource:
        return self._stream(
            parts_message(
                parts,
                task_id=task_id,
                context_id=context_id,
                participant=self.participant,
                speak=speak,
            )
        )

    def send_action(self, action: Action, *, task_id: str, context_id: str) -> EventSource:
        return self._stream(
            action_message(
                action, task_id=task_id, context_id=context_id, participant=self.participant
            )
        )

    async def subscribe(self, task_id: str) -> EventSource:
        async for response in self._client.subscribe(SubscribeToTaskRequest(id=task_id)):
            yield unwrap(response)

    async def cancel(self, task_id: str) -> Task:
        return await self._client.cancel_task(CancelTaskRequest(id=task_id))

    def complete(self, task_id: str) -> EventSource:
        return self._stream(complete_message(task_id, participant_id=self.participant or ""))

    async def get_task(self, task_id: str) -> Task:
        return await self._client.get_task(GetTaskRequest(id=task_id, history_length=0))

    def commands(self) -> tuple[CommandSpec, ...]:
        return card_commands(self.card) if self.card is not None else ()

    def media(self) -> MediaExtensionParams | None:
        return card_media(self.card) if self.card is not None else None

    async def get_media(self, url: str) -> MediaSource:
        """The medium's bytes as they arrive. Only the agent's own origin is asked, so the
        participant header never goes to another host; an error status raises."""
        if not same_origin(url, self.base_url):
            raise httpx.InvalidURL(f"media URL {url!r} is not on the agent's origin")
        async with self._http.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk

    async def close(self) -> None:
        await self._client.close()
        await self._http.aclose()


def same_origin(url: str, base: str) -> bool:
    a, b = urlsplit(url), urlsplit(base)
    return bool(b.netloc) and (a.scheme, a.netloc) == (b.scheme, b.netloc)


class ScriptedClient:
    """Replays scripted events; records what the TUI sent (tests and snapshots)."""

    def __init__(
        self,
        scripts: Sequence[Sequence[A2AEvent]] = (),
        *,
        commands: Sequence[CommandSpec] = (),
        tasks: Sequence[Task] = (),
        follow: Mapping[str, Sequence[A2AEvent]] | None = None,
        media: MediaExtensionParams | None = None,
        files: Mapping[str, Sequence[bytes | Exception | asyncio.Event]] | None = None,
    ) -> None:
        self._scripts = [list(s) for s in scripts]
        self._media = media
        self._files = {k: list(v) for k, v in (files or {}).items()}
        self._streams = {k: list(v) for k, v in (follow or {}).items()}
        self._commands = tuple(commands)
        self._tasks = {t.id: t for t in tasks}
        self.sent: list[str] = []  # the text of each message
        self.sent_parts: list[list[Part]] = []
        self.spoken: list[bool] = []  # the speaker setting of each message
        self.media_fetched: list[str] = []
        self.actions: list[Action] = []
        self.cancelled: list[str] = []
        self.completed: list[str] = []
        self.fetched: list[str] = []
        self.subscribed: list[str] = []

    def _next(self) -> list[A2AEvent]:
        return self._scripts.pop(0) if self._scripts else []

    async def _replay(self, events: Sequence[A2AEvent]) -> EventSource:
        for event in events:
            yield event

    def send(
        self, parts: Sequence[Part], *, task_id: str | None, context_id: str, speak: bool = False
    ) -> EventSource:
        self.sent.append(text_of(parts))
        self.sent_parts.append(list(parts))
        self.spoken.append(speak)
        return self._replay(self._next())

    def send_action(self, action: Action, *, task_id: str, context_id: str) -> EventSource:
        self.actions.append(action)
        return self._replay(self._next())

    def subscribe(self, task_id: str) -> EventSource:
        """``follow``'s events for ``task_id``, once; then an empty stream."""
        self.subscribed.append(task_id)
        return self._replay(self._streams.pop(task_id, []))

    async def cancel(self, task_id: str) -> Task:
        self.cancelled.append(task_id)
        return Task(id=task_id, status=TaskStatus(state=TaskState.TASK_STATE_CANCELED))

    def complete(self, task_id: str) -> EventSource:
        self.completed.append(task_id)
        return self._replay(self._next())

    async def get_task(self, task_id: str) -> Task:
        self.fetched.append(task_id)
        if task_id not in self._tasks:
            raise TaskNotFoundError(message=f"task {task_id} not found")
        return self._tasks[task_id]

    def commands(self) -> tuple[CommandSpec, ...]:
        return self._commands

    def media(self) -> MediaExtensionParams | None:
        return self._media

    async def get_media(self, url: str) -> MediaSource:
        """``files``' chunks for ``url``; an exception among them is raised there (a
        stream aborted midway), an ``asyncio.Event`` holds the stream open until it is
        set (a growing object); an unknown URL is a 404."""
        self.media_fetched.append(url)
        if url not in self._files:
            request = httpx.Request("GET", url)
            raise httpx.HTTPStatusError(
                "404 Not Found", request=request, response=httpx.Response(404, request=request)
            )
        for chunk in self._files[url]:
            if isinstance(chunk, asyncio.Event):
                await chunk.wait()
            elif isinstance(chunk, Exception):
                raise chunk
            else:
                yield chunk

    async def close(self) -> None:
        return None


__all__ = [
    "A2AClientPort",
    "Attachment",
    "EventSource",
    "MediaSource",
    "ScriptedClient",
    "SdkClient",
    "action_message",
    "card_commands",
    "card_media",
    "file_part",
    "parts_message",
    "same_origin",
    "text_of",
    "user_message",
    "user_parts",
]
