"""``RemoteAgent`` (R7): an A2A 1.0 agent reached through the official client.

The card is fetched from ``/.well-known/agent-card.json`` and validated before anything
is sent (R7.2): a card that declares a security scheme or requires an extension the
harness does not implement is refused with ``UnsupportedExtensionError`` (R7.4, abuse
case 5). ``A2A-Extensions`` names only extensions the card advertises (R7.5); the
client sends ``A2A-Version: 1.0`` on every request (R7.1).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from typing import Literal

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.client.client import Client as A2AClient
from a2a.client.client import ClientCallContext
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetTaskRequest,
    Message,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
)

from tiny_harness.errors import UnsupportedExtensionError
from tiny_harness.harness.agents.base import SUPPORTED_EXTENSIONS, A2AEvent, Agent
from tiny_harness.harness.entities import EntityKind, EntityRef

EXTENSIONS_HEADER = "A2A-Extensions"
PARTICIPANT_HEADER = "X-Participant-Id"

type UpdateMode = Literal["auto", "follow", "off"]


def validate_card(card: AgentCard, *, supported: Sequence[str] = SUPPORTED_EXTENSIONS) -> None:
    """Refuse a card the harness cannot honour, before any credential or message leaves."""
    if card.security_schemes or card.security_requirements:
        raise UnsupportedExtensionError(
            "remote agent card declares a security scheme; credential handling is not implemented",
            agent=card.name,
        )
    for extension in card.capabilities.extensions:
        if extension.required and extension.uri not in supported:
            raise UnsupportedExtensionError(
                "remote agent card requires an extension the harness does not implement",
                agent=card.name,
                extension=extension.uri,
            )


def unwrap(response: StreamResponse) -> A2AEvent:
    if response.HasField("task"):
        return response.task
    if response.HasField("message"):
        return response.message
    if response.HasField("status_update"):
        return response.status_update
    return response.artifact_update


class RemoteAgent(Agent):
    def __init__(
        self,
        ref: EntityRef,
        agent_card: AgentCard,
        *,
        client: A2AClient | None,
        updates: UpdateMode = "auto",
        follow_interval: timedelta = timedelta(seconds=5),
    ) -> None:
        validate_card(agent_card)
        super().__init__(ref, agent_card)
        self._client: A2AClient | None = client
        self.updates: UpdateMode = updates  # how a parked task is watched (issue-27 R4)
        self.follow_interval = follow_interval
        self._pending: tuple[str, httpx.AsyncClient] | None = None
        self._lock: asyncio.Lock | None = None

    @classmethod
    async def connect(
        cls,
        agent_id: str,
        url: str,
        *,
        http: httpx.AsyncClient | None = None,
        version: str | None = None,
        updates: UpdateMode = "auto",
        follow_interval: timedelta = timedelta(seconds=5),
    ) -> RemoteAgent:
        http = http or httpx.AsyncClient(timeout=60)
        card = await A2ACardResolver(http, url).get_agent_card()
        return cls.from_card(
            agent_id,
            card,
            http=http,
            version=version,
            updates=updates,
            follow_interval=follow_interval,
        )

    @classmethod
    def from_card(
        cls,
        agent_id: str,
        card: AgentCard,
        *,
        http: httpx.AsyncClient | None = None,
        version: str | None = None,
        updates: UpdateMode = "auto",
        follow_interval: timedelta = timedelta(seconds=5),
    ) -> RemoteAgent:
        """An agent whose card is already known: the harness itself (issue-34 R7.1)."""
        validate_card(card)
        http = http or httpx.AsyncClient(timeout=60)
        factory = ClientFactory(
            ClientConfig(
                httpx_client=http,
                streaming=True,
                supported_protocol_bindings=["JSONRPC", "HTTP+JSON"],
            )
        )
        ref = EntityRef(kind=EntityKind.AGENT, id=agent_id, version=version)
        return cls(
            ref, card, client=factory.create(card), updates=updates, follow_interval=follow_interval
        )

    @classmethod
    def deferred(
        cls,
        agent_id: str,
        url: str,
        *,
        http: httpx.AsyncClient | None = None,
        version: str | None = None,
        updates: UpdateMode = "auto",
        follow_interval: timedelta = timedelta(seconds=5),
    ) -> RemoteAgent:
        """An agent whose card is fetched on first use, not now (issue-36 R6.1): an agent
        mounted in the same service as this one is not listening while that service
        starts. Every call resolves the card first; a card that fails validation fails that
        call, as it would have failed the start."""
        ref = EntityRef(kind=EntityKind.AGENT, id=agent_id, version=version)
        agent = cls(
            ref,
            AgentCard(name=agent_id),
            client=None,
            updates=updates,
            follow_interval=follow_interval,
        )
        agent._pending = (url, http or httpx.AsyncClient(timeout=60))
        return agent

    async def resolve_card(self) -> None:
        """Fetch a deferred agent's card and build its client, once; a no-op otherwise."""
        if self._pending is None:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            pending = self._pending  # another caller may have resolved it while we waited
            if pending is not None:  # pyright: ignore[reportUnnecessaryComparison]
                url, http = pending
                self.agent_card, self._client = await _resolve(http, url)
                self._pending = None

    async def ensure_connected(self) -> A2AClient:
        """The A2A client, resolving a deferred agent's card the first time."""
        await self.resolve_card()
        assert self._client is not None
        return self._client

    @property
    def push_supported(self) -> bool:
        return self.agent_card.capabilities.push_notifications

    @property
    def advertised_extensions(self) -> frozenset[str]:
        return frozenset(e.uri for e in self.agent_card.capabilities.extensions)

    def _context(
        self, extensions: Sequence[str], *, participant: str | None = None
    ) -> ClientCallContext | None:
        parameters: dict[str, str] = {}
        active = [uri for uri in extensions if uri in self.advertised_extensions]
        if active:
            parameters[EXTENSIONS_HEADER] = ", ".join(active)
        if participant:
            # A tiny-harness peer answers a task-scoped call only for a participant
            # (decision-003): the harness asserts the id it delegated as.
            parameters[PARTICIPANT_HEADER] = participant
        return ClientCallContext(service_parameters=parameters) if parameters else None

    async def send_message(
        self, request: Message, *, extensions: Sequence[str] = ()
    ) -> AsyncIterator[A2AEvent]:
        # The header asserts the participant the message names: a tiny-harness peer
        # refuses a reply to an existing task without it (decision-003).
        client = await self.ensure_connected()
        claimed = request.metadata.fields.get("participant_id")
        participant = claimed.string_value if claimed is not None else None
        context = self._context(extensions, participant=participant)
        async for response in client.send_message(
            SendMessageRequest(message=request), context=context
        ):
            yield unwrap(response)

    async def cancel_task(self, task_id: str, *, participant: str | None = None) -> Task:
        client = await self.ensure_connected()
        return await client.cancel_task(
            CancelTaskRequest(id=task_id), context=self._context((), participant=participant)
        )

    async def get_task(self, task_id: str, *, participant: str | None = None) -> Task:
        client = await self.ensure_connected()
        return await client.get_task(
            GetTaskRequest(id=task_id), context=self._context((), participant=participant)
        )

    async def subscribe(
        self,
        task_id: str,
        *,
        extensions: Sequence[str] = (),
        participant: str | None = None,
    ) -> AsyncIterator[A2AEvent]:
        client = await self.ensure_connected()
        context = self._context(extensions, participant=participant)
        async for response in client.subscribe(SubscribeToTaskRequest(id=task_id), context=context):
            yield unwrap(response)

    async def set_push_config(
        self, task_id: str, url: str, token: str, *, participant: str | None = None
    ) -> str:
        """Register ``url`` for the task's updates (issue-27 R1); the remote assigns the
        config id. The token goes to the remote agent and nowhere else."""
        client = await self.ensure_connected()
        config = await client.create_task_push_notification_config(
            TaskPushNotificationConfig(task_id=task_id, url=url, token=token),
            context=self._context((), participant=participant),
        )
        return config.id

    async def delete_push_config(
        self, task_id: str, config_id: str, *, participant: str | None = None
    ) -> None:
        client = await self.ensure_connected()
        await client.delete_task_push_notification_config(
            DeleteTaskPushNotificationConfigRequest(task_id=task_id, id=config_id),
            context=self._context((), participant=participant),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        elif self._pending is not None:
            await self._pending[1].aclose()


async def _resolve(http: httpx.AsyncClient, url: str) -> tuple[AgentCard, A2AClient]:
    """Fetch and check the card at ``url``, then build a client for it."""
    card = await A2ACardResolver(http, url).get_agent_card()
    validate_card(card)
    factory = ClientFactory(
        ClientConfig(
            httpx_client=http,
            streaming=True,
            supported_protocol_bindings=["JSONRPC", "HTTP+JSON"],
        )
    )
    return card, factory.create(card)


__all__ = [
    "EXTENSIONS_HEADER",
    "PARTICIPANT_HEADER",
    "RemoteAgent",
    "UpdateMode",
    "unwrap",
    "validate_card",
]
