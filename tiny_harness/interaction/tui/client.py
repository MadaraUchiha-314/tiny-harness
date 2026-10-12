"""The TUI's A2A client port (R20.2): the SDK client over JSON-RPC with streaming and
``A2A-Version: 1.0``, plus a scripted client for tests and snapshots.

issue-25: ``complete`` sends the same control envelope any A2A client can (R5.1), and
``commands`` reads the card's commands extension for ``/`` completion (R6.7)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Protocol

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
from tiny_harness.interaction.a2ui import A2UI_MEDIA_TYPE, Action
from tiny_harness.service.inbox import complete_message

type EventSource = AsyncIterator[A2AEvent]


class A2AClientPort(Protocol):
    def send(self, text: str, *, task_id: str | None, context_id: str) -> EventSource: ...

    def send_action(self, action: Action, *, task_id: str, context_id: str) -> EventSource: ...

    def subscribe(self, task_id: str) -> EventSource: ...

    async def cancel(self, task_id: str) -> Task: ...

    def complete(self, task_id: str) -> EventSource: ...

    async def get_task(self, task_id: str) -> Task: ...

    def commands(self) -> tuple[CommandSpec, ...]: ...

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


def user_message(
    text: str, *, task_id: str | None, context_id: str, participant: str | None
) -> Message:
    message = Message(
        message_id=uuid.uuid4().hex,
        context_id=context_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(text=text)],
    )
    if task_id:
        message.task_id = task_id
    if participant:
        message.metadata.update({"participant_id": participant})
    return message


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
    ) -> None:
        self._client = client
        self._http = http
        self.participant = participant
        self.card = card

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
        return cls(client, http=http, participant=participant, card=card)

    async def _stream(self, message: Message) -> EventSource:
        async for response in self._client.send_message(SendMessageRequest(message=message)):
            yield unwrap(response)

    def send(self, text: str, *, task_id: str | None, context_id: str) -> EventSource:
        return self._stream(
            user_message(text, task_id=task_id, context_id=context_id, participant=self.participant)
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

    async def close(self) -> None:
        await self._client.close()
        await self._http.aclose()


class ScriptedClient:
    """Replays scripted events; records what the TUI sent (tests and snapshots)."""

    def __init__(
        self,
        scripts: Sequence[Sequence[A2AEvent]] = (),
        *,
        commands: Sequence[CommandSpec] = (),
        tasks: Sequence[Task] = (),
        follow: Mapping[str, Sequence[A2AEvent]] | None = None,
    ) -> None:
        self._scripts = [list(s) for s in scripts]
        self._streams = {k: list(v) for k, v in (follow or {}).items()}
        self._commands = tuple(commands)
        self._tasks = {t.id: t for t in tasks}
        self.sent: list[str] = []
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

    def send(self, text: str, *, task_id: str | None, context_id: str) -> EventSource:
        self.sent.append(text)
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

    async def close(self) -> None:
        return None


__all__ = [
    "A2AClientPort",
    "EventSource",
    "ScriptedClient",
    "SdkClient",
    "action_message",
    "card_commands",
    "user_message",
]
