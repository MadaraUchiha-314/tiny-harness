"""Channels, participants' messages and help requests (R12, R13).

A channel is a set of participants the harness manages; the harness and the participants
send and receive through it. Membership is the boundary (abuse case 4): a message from a
non-member is refused with the same error whether or not the channel exists. The default
medium is A2A itself (``A2AChannel``): a send becomes an A2A message event on the task
carrying the channel extension's data part, persisted before delivery; a participant
sends by calling ``SendMessage`` on the task with the same part.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tiny_harness.errors import ChannelMembershipError
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef
from tiny_harness.harness.persistence import ChannelMessageRecord, Store
from tiny_harness.harness.tools import ContentPart

CHANNEL_EXT_URI = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/channel/v1"
CHANNEL_EXT_MEDIA_TYPE = "application/vnd.tiny-harness.channel+json"
MessageKind = Literal["message", "help_request", "help_reply"]


class ChannelMessage(BaseModel, frozen=True):
    id: str
    channel_id: str
    sender: str
    parts: tuple[ContentPart, ...]
    at: datetime
    kind: MessageKind = "message"

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.parts if p.kind == "text" and p.text is not None)


class ChannelMessageData(BaseModel, frozen=True):
    """The A2A extension's data part (``application/vnd.tiny-harness.channel+json``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel_id: str
    sender: str
    kind: MessageKind = "message"
    text: str = ""
    parts: tuple[ContentPart, ...] = ()
    in_reply_to: str | None = None


class Channel(Entity):
    """Members are participant ids; ``pull`` channels are polled by the heartbeat (R16)."""

    kind = EntityKind.CHANNEL
    pull: bool = False

    def __init__(self, ref: EntityRef, *, task_id: str, members: Sequence[str]) -> None:
        super().__init__(ref)
        self.task_id = task_id
        self.members = frozenset(members)

    @property
    def id(self) -> str:
        return self.ref.id

    def check_member(self, participant_id: str | None) -> None:
        """The uniform refusal: the same error for a non-member and an unknown sender."""
        if participant_id is None or participant_id not in self.members:
            raise ChannelMembershipError("not a member of this channel", channel=self.id)

    @abstractmethod
    async def send(self, message: ChannelMessage) -> None: ...

    @abstractmethod
    def receive(self) -> AsyncIterator[ChannelMessage]: ...


Emitter = Callable[[ChannelMessage], Awaitable[None]]
"""Hands a message to the task's A2A event stream (the ``emit_event`` activity)."""


class A2AChannel(Channel):
    """The default medium: persist, then emit as an A2A message event (R13.2)."""

    def __init__(
        self,
        ref: EntityRef,
        *,
        task_id: str,
        context_id: str,
        members: Sequence[str],
        store: Store,
        emitter: Emitter,
    ) -> None:
        super().__init__(ref, task_id=task_id, members=members)
        self._context_id = context_id
        self._store = store
        self._emitter = emitter
        self._inbound: list[ChannelMessage] = []

    async def send(self, message: ChannelMessage) -> None:
        self.check_member(message.sender)
        await self._store.put(
            ChannelMessageRecord(
                id=message.id,
                context_id=self._context_id,
                task_id=self.task_id,
                created_at=message.at,
                channel_id=self.id,
                sender=message.sender,
                message_kind=message.kind,
                parts=message.parts,
            )
        )
        await self._emitter(message)

    async def accept(self, message: ChannelMessage) -> None:
        """An inbound message from a participant (through ``SendMessage``)."""
        self.check_member(message.sender)
        await self._store.put(
            ChannelMessageRecord(
                id=message.id,
                context_id=self._context_id,
                task_id=self.task_id,
                created_at=message.at,
                channel_id=self.id,
                sender=message.sender,
                message_kind=message.kind,
                parts=message.parts,
            )
        )
        self._inbound.append(message)

    async def receive(self) -> AsyncIterator[ChannelMessage]:
        while self._inbound:
            yield self._inbound.pop(0)


class HelpRoute(StrEnum):
    ASK = "ask"
    CREATE_TASK = "create_task"


class HelpNeed(BaseModel, frozen=True):
    """What the harness needs from a participant, before routing."""

    question: str
    options: tuple[str, ...] = ()
    blocking_work: bool | None = None
    participant_id: str | None = None


class HelpDecision(BaseModel, frozen=True):
    """The routed need: ask on a channel, or create a task for the participant (R12.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route: HelpRoute
    participant_id: str
    question: str | None = None
    options: tuple[str, ...] = ()
    name: str | None = None
    goal: str | None = None
    acceptance_criteria: tuple[str, ...] = ()
    reason: str = ""


def validate_decision(need: HelpNeed, decision: HelpDecision) -> str | None:
    """The validator that always runs: an ASK cannot stand in for work another
    participant must do; a CREATE_TASK needs a goal. Returns the objection, or None."""
    if decision.route is HelpRoute.ASK:
        if need.blocking_work is True:
            return "the need is work another participant must finish; route must be create_task"
        if not (decision.question or need.question):
            return "an ask needs a question"
    else:
        if not decision.goal and not need.question:
            return "a created task needs a goal"
    return None


__all__ = [
    "CHANNEL_EXT_MEDIA_TYPE",
    "CHANNEL_EXT_URI",
    "A2AChannel",
    "Channel",
    "ChannelMessage",
    "ChannelMessageData",
    "Emitter",
    "HelpDecision",
    "HelpNeed",
    "HelpRoute",
    "MessageKind",
    "validate_decision",
]
