"""The records the store holds (R11.1, R11.4, R11.5) and the push-token cipher.

Temporal history is the replay source; the store is the read model that outlives the
workflow: task records on every state change, plans when attached or changed, the state
summary per turn, channel messages before delivery, inbox audit rows, compaction records
and push-notification configs. No record field is a credential, with one exception: a
push config's client-supplied callback credential, held as ``SecretStr`` so it is masked
wherever a record is printed, and protected at rest by the store (issue-23).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from a2a.types import Task
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_serializer

from tiny_harness.harness.core import (
    AgentState,
    CompactionRecord,
    Plan,
    SchemaValidated,
    proto_json,
)
from tiny_harness.harness.tools import ContentPart
from tiny_harness.jsontypes import JsonObject


class RecordKind(StrEnum):
    TASKS = "tasks"
    PLANS = "plans"
    STATE = "state"
    CHANNEL_MESSAGES = "channel_messages"
    INBOX_AUDIT = "inbox_audit"
    COMPACTIONS = "compactions"
    PUSH_CONFIGS = "push_configs"


class RecordBase(BaseModel, frozen=True):
    model_config = ConfigDict(frozen=True)

    id: str
    context_id: str
    task_id: str
    created_at: datetime


class TaskRecord(RecordBase, frozen=True):
    """The A2A task proto (extension in its metadata) plus its emitted event log."""

    kind: Literal["tasks"] = "tasks"
    task: Annotated[Task, *proto_json(Task)]
    state_name: str
    events: tuple[JsonObject, ...] = ()


class PlanRecord(RecordBase, frozen=True):
    kind: Literal["plans"] = "plans"
    plan: Plan
    turn: int


class StateRecord(RecordBase, frozen=True):
    """The typed subset and the summary, not the raw history (Temporal holds that)."""

    kind: Literal["state"] = "state"
    turn: int
    summary: str
    data: SchemaValidated
    loaded_skills: tuple[str, ...]

    @classmethod
    def from_state(cls, state: AgentState, *, context_id: str, at: datetime) -> StateRecord:
        return cls(
            id=f"{state.task_id}:{state.turn}",
            context_id=context_id,
            task_id=state.task_id,
            created_at=at,
            turn=state.turn,
            summary=state.summary,
            data=state.data,
            loaded_skills=tuple(s.name for s in state.loaded_skills),
        )


class ChannelMessageRecord(RecordBase, frozen=True):
    kind: Literal["channel_messages"] = "channel_messages"
    channel_id: str
    sender: str
    message_kind: Literal["message", "help_request", "help_reply"]
    parts: tuple[ContentPart, ...]


class InboxAuditRecord(RecordBase, frozen=True):
    kind: Literal["inbox_audit"] = "inbox_audit"
    message_id: str
    participant_id: str | None
    accepted: bool
    reason: str = ""


class CompactionStoreRecord(RecordBase, frozen=True):
    kind: Literal["compactions"] = "compactions"
    record: CompactionRecord


class PushConfigRecord(RecordBase, frozen=True):
    """A push-notification config; ``token`` and ``authentication`` (the A2A
    ``AuthenticationInfo`` as proto JSON) are the client's callback credential, kept as
    supplied and revealed only when the store serialises the record."""

    kind: Literal["push_configs"] = "push_configs"
    config_id: str
    url: str
    token: SecretStr = SecretStr("")
    authentication: SecretStr = SecretStr("")
    # Written by 0.5.x and earlier, encrypted under a key that no longer exists; read
    # only to recognise such a row so it is dropped rather than delivered (issue-23 R4).
    token_ciphertext: str = Field(default="", exclude=True)
    authentication_ciphertext: str = Field(default="", exclude=True)

    @field_serializer("token", "authentication", when_used="json")
    def _reveal(self, value: SecretStr) -> str:
        return value.get_secret_value()

    @property
    def legacy(self) -> bool:
        return bool(self.token_ciphertext or self.authentication_ciphertext)


type Record = (
    TaskRecord
    | PlanRecord
    | StateRecord
    | ChannelMessageRecord
    | InboxAuditRecord
    | CompactionStoreRecord
    | PushConfigRecord
)

RECORD_TYPES: dict[RecordKind, type[RecordBase]] = {
    RecordKind.TASKS: TaskRecord,
    RecordKind.PLANS: PlanRecord,
    RecordKind.STATE: StateRecord,
    RecordKind.CHANNEL_MESSAGES: ChannelMessageRecord,
    RecordKind.INBOX_AUDIT: InboxAuditRecord,
    RecordKind.COMPACTIONS: CompactionStoreRecord,
    RecordKind.PUSH_CONFIGS: PushConfigRecord,
}


def kind_of(record: RecordBase) -> RecordKind:
    for kind, record_type in RECORD_TYPES.items():
        if isinstance(record, record_type):
            return kind
    raise TypeError(f"unknown record type {type(record).__name__}")


class Filter(BaseModel, frozen=True):
    """A query: by context, by task, newer than ``since``, at most ``limit`` rows."""

    context_id: str | None = None
    task_id: str | None = None
    since: datetime | None = None
    limit: int = Field(default=100, ge=1, le=1000)


__all__ = [
    "RECORD_TYPES",
    "ChannelMessageRecord",
    "CompactionStoreRecord",
    "Filter",
    "InboxAuditRecord",
    "PlanRecord",
    "PushConfigRecord",
    "Record",
    "RecordBase",
    "RecordKind",
    "StateRecord",
    "TaskRecord",
    "kind_of",
]
