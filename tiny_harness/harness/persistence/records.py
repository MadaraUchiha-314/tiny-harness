"""The records the store holds (R11.1, R11.4, R11.5) and the push-token cipher.

Temporal history is the replay source; the store is the read model that outlives the
workflow: task records on every state change, plans when attached or changed, the state
summary per turn, channel messages before delivery, inbox audit rows, compaction records
and push-notification configs. No record field is a credential, with one encrypted
exception: a push config's client-supplied callback token, stored AES-GCM encrypted
under ``TINY_HARNESS_PUSH_KEY`` and decrypted only inside the ``emit_event`` activity.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from a2a.types import Task
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from tiny_harness.errors import ConfigError
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
    """A push-notification config; ``token`` and ``authentication`` are ciphertext."""

    kind: Literal["push_configs"] = "push_configs"
    config_id: str
    url: str
    token_ciphertext: str = ""
    authentication_ciphertext: str = ""


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


class PushTokenCipher:
    """AES-GCM for push-config credentials at rest (design.md § Security design)."""

    def __init__(self, key: SecretStr) -> None:
        try:
            raw = base64.b64decode(key.get_secret_value(), validate=True)
        except ValueError as exc:
            raise ConfigError("push key must be base64", variable="TINY_HARNESS_PUSH_KEY") from exc
        if len(raw) not in (16, 24, 32):
            raise ConfigError(
                "push key must decode to 16, 24 or 32 bytes", variable="TINY_HARNESS_PUSH_KEY"
            )
        self._aead = AESGCM(raw)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        nonce = os.urandom(12)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), None)
        return base64.b64encode(nonce + sealed).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        blob = base64.b64decode(ciphertext)
        return self._aead.decrypt(blob[:12], blob[12:], None).decode()


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
    "PushTokenCipher",
    "Record",
    "RecordBase",
    "RecordKind",
    "StateRecord",
    "TaskRecord",
    "kind_of",
]
