"""The agent entity (R1.1, R7): the A2A SDK's own types, nothing mirrored.

``A2AEvent`` is what a task emits and what a client receives: a ``Message``, a ``Task``,
or a status or artifact update. ``LocalAgent`` (the harness itself) and ``RemoteAgent``
(an A2A client) implement ``send_message`` and ``cancel_task`` over it.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Final

from a2a.types import AgentCard, Message, Task, TaskArtifactUpdateEvent, TaskStatusUpdateEvent

from tiny_harness.harness.channels import CHANNEL_EXT_URI
from tiny_harness.harness.core import TASK_EXT_URI
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef

type A2AEvent = Message | Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent

A2UI_EXT_URI: Final = "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
SUPPORTED_EXTENSIONS: Final[tuple[str, ...]] = (TASK_EXT_URI, CHANNEL_EXT_URI, A2UI_EXT_URI)
"""Every extension the harness implements: what the card advertises and what a remote
card may require without being refused (R7.4, R14.3)."""


class Agent(Entity):
    """An agent reachable over A2A, local or remote; its card is the contract."""

    kind = EntityKind.AGENT

    def __init__(self, ref: EntityRef, agent_card: AgentCard) -> None:
        super().__init__(ref)
        self.agent_card = agent_card

    @abstractmethod
    def send_message(
        self, request: Message, *, extensions: Sequence[str] = ()
    ) -> AsyncIterator[A2AEvent]: ...

    @abstractmethod
    async def cancel_task(self, task_id: str) -> Task: ...


__all__ = ["A2UI_EXT_URI", "SUPPORTED_EXTENSIONS", "A2AEvent", "Agent"]
