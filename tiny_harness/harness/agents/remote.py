"""``RemoteAgent`` (R7): an A2A 1.0 agent reached through the official client.

The card is fetched from ``/.well-known/agent-card.json`` and validated before anything
is sent (R7.2): a card that declares a security scheme or requires an extension the
harness does not implement is refused with ``UnsupportedExtensionError`` (R7.4, abuse
case 5). ``A2A-Extensions`` names only extensions the card advertises (R7.5); the
client sends ``A2A-Version: 1.0`` on every request (R7.1).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.client.client import Client as A2AClient
from a2a.client.client import ClientCallContext
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    Message,
    SendMessageRequest,
    StreamResponse,
    Task,
)

from tiny_harness.errors import UnsupportedExtensionError
from tiny_harness.harness.agents.base import SUPPORTED_EXTENSIONS, A2AEvent, Agent
from tiny_harness.harness.entities import EntityKind, EntityRef

EXTENSIONS_HEADER = "A2A-Extensions"


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
    def __init__(self, ref: EntityRef, agent_card: AgentCard, *, client: A2AClient) -> None:
        validate_card(agent_card)
        super().__init__(ref, agent_card)
        self._client = client

    @classmethod
    async def connect(
        cls,
        agent_id: str,
        url: str,
        *,
        http: httpx.AsyncClient | None = None,
        version: str | None = None,
    ) -> RemoteAgent:
        http = http or httpx.AsyncClient(timeout=60)
        card = await A2ACardResolver(http, url).get_agent_card()
        validate_card(card)
        factory = ClientFactory(
            ClientConfig(
                httpx_client=http,
                streaming=True,
                supported_protocol_bindings=["JSONRPC", "HTTP+JSON"],
            )
        )
        ref = EntityRef(kind=EntityKind.AGENT, id=agent_id, version=version)
        return cls(ref, card, client=factory.create(card))

    @property
    def advertised_extensions(self) -> frozenset[str]:
        return frozenset(e.uri for e in self.agent_card.capabilities.extensions)

    def _context(self, extensions: Sequence[str]) -> ClientCallContext | None:
        active = [uri for uri in extensions if uri in self.advertised_extensions]
        if not active:
            return None
        return ClientCallContext(service_parameters={EXTENSIONS_HEADER: ", ".join(active)})

    async def send_message(
        self, request: Message, *, extensions: Sequence[str] = ()
    ) -> AsyncIterator[A2AEvent]:
        context = self._context(extensions)
        async for response in self._client.send_message(
            SendMessageRequest(message=request), context=context
        ):
            yield unwrap(response)

    async def cancel_task(self, task_id: str) -> Task:
        return await self._client.cancel_task(CancelTaskRequest(id=task_id))

    async def close(self) -> None:
        await self._client.close()


__all__ = ["EXTENSIONS_HEADER", "RemoteAgent", "unwrap", "validate_card"]
