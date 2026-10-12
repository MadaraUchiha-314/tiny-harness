"""Inbox intake: the event envelope and what it does to a task (R15.1, R15.3).

A message may carry one ``application/vnd.tiny-harness.event+json`` data part, the
*event envelope*: a ``task`` payload creates the extension data of a new task or updates
an existing task's (name, description and acceptance criteria by any participant;
participants and their roles only by an admin, abuse case 4), and a ``status_update`` or
``artifact_update`` payload from a participant is recorded into the task's history as a
framed event, so it is never silently dropped. Routing such updates to a remote
sub-task is not built in this work item.

A ``control`` envelope (issue-25 R5.1) carries ``action`` and nothing else: today only
``complete``, a participant asking to complete the task. Its shape is closed, so an
unknown action, a payload or any extra field is refused.
"""

from __future__ import annotations

from typing import Literal, cast

from a2a.types import Message
from a2a.utils.errors import InvalidParamsError
from google.protobuf import json_format
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from tiny_harness.harness.core import Role, TaskExtensionData
from tiny_harness.jsontypes import JsonObject

EVENT_MEDIA_TYPE = "application/vnd.tiny-harness.event+json"
OPEN_FIELDS: frozenset[str] = frozenset({"name", "description", "acceptance_criteria"})
ADMIN_FIELDS: frozenset[str] = frozenset({"participants"})
SERVER_FIELDS: frozenset[str] = frozenset({"lifecycle", "model", "reasoning_effort"})
"""Set only by the server (R3, R7.3): any envelope carrying one is refused whole."""


def server_controlled(payload: JsonObject) -> list[str]:
    """The server-controlled fields ``payload`` tries to set, sorted."""
    return sorted(SERVER_FIELDS & set(payload))


class EventEnvelope(BaseModel):
    """The task extension's event part (R15.1). ``task``, ``status_update`` and
    ``artifact_update`` carry a ``payload``; ``control`` carries only an ``action``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["task", "status_update", "artifact_update", "control"]
    payload: JsonObject = Field(default_factory=dict)
    action: Literal["complete"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> EventEnvelope:
        if self.kind == "control":
            if self.action is None or "payload" in self.model_fields_set:
                raise ValueError("a control envelope carries an action and nothing else")
        elif self.action is not None or "payload" not in self.model_fields_set:
            raise ValueError(f"a {self.kind} envelope carries a payload and no action")
        return self


class EnvelopeRefused(Exception):
    """A ``task`` envelope the task does not accept; ``reason`` is recorded with the refusal."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def envelope_of(message: Message) -> EventEnvelope | None:
    for part in message.parts:
        if part.HasField("data") and part.media_type == EVENT_MEDIA_TYPE:
            raw = json_format.MessageToDict(part.data)
            try:
                return EventEnvelope.model_validate(raw)
            except ValidationError as exc:
                raise InvalidParamsError(message=f"invalid event envelope: {exc}") from exc
    return None


def controls_task(ext: TaskExtensionData, participant_id: str | None) -> bool:
    """Whether ``participant_id`` may complete or cancel the task: on it in a role other
    than ``watcher`` (abuse case 4)."""
    return participant_id is not None and any(
        p.id == participant_id and p.role is not Role.WATCHER for p in ext.participants
    )


def apply_task_envelope(
    ext: TaskExtensionData, payload: JsonObject, *, actor: str
) -> TaskExtensionData:
    """The extension after a ``task`` envelope from ``actor``, who is a participant.

    Name, description and acceptance criteria are open to every participant; a change of
    participants or roles needs an admin; the server-controlled fields (``SERVER_FIELDS``)
    are refused from anyone; anything else in the payload is refused.
    """
    fields = set(payload)
    refused = server_controlled(payload)
    if refused:
        raise EnvelopeRefused(f"task envelope cannot set server-controlled {', '.join(refused)}")
    unknown = fields - OPEN_FIELDS - ADMIN_FIELDS
    if unknown:
        raise EnvelopeRefused(f"task envelope cannot change {', '.join(sorted(unknown))}")
    if fields & ADMIN_FIELDS and not ext.has_role(actor, Role.ADMIN):
        raise EnvelopeRefused("admin required to change participants")
    merged: JsonObject = {**cast(JsonObject, ext.model_dump(mode="json")), **payload}
    try:
        return TaskExtensionData.model_validate(merged)
    except ValidationError as exc:
        raise EnvelopeRefused(f"invalid task extension: {exc.error_count()} error(s)") from exc


__all__ = [
    "ADMIN_FIELDS",
    "EVENT_MEDIA_TYPE",
    "OPEN_FIELDS",
    "SERVER_FIELDS",
    "EnvelopeRefused",
    "EventEnvelope",
    "apply_task_envelope",
    "controls_task",
    "envelope_of",
    "server_controlled",
]
