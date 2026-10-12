"""Abuse case 1 (and its siblings): ``lifecycle``, ``model`` and ``reasoning_effort`` are
server-controlled; no participant's ``task`` envelope may set them (R3, R7.3)."""

from __future__ import annotations

import pytest
from a2a.types import Message, Part
from a2a.utils.errors import UnsupportedOperationError
from google.protobuf import struct_pb2

from tiny_harness.harness.core import Participant, Role, TaskExtensionData
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.executor import extension_from_envelope
from tiny_harness.service.inbox import (
    EVENT_MEDIA_TYPE,
    SERVER_FIELDS,
    EnvelopeRefused,
    EventEnvelope,
    apply_task_envelope,
)

ATTEMPTS: tuple[JsonObject, ...] = (
    {"lifecycle": "delegated"},
    {"model": "evil-model"},
    {"reasoning_effort": "high"},
)


def test_the_server_controlled_fields_are_exactly_three() -> None:
    assert frozenset({"lifecycle", "model", "reasoning_effort"}) == SERVER_FIELDS


@pytest.mark.parametrize("extra", ATTEMPTS)
def test_a_first_message_envelope_setting_one_is_refused(extra: JsonObject) -> None:
    payload: JsonObject = {"name": "Audit", "goal": "Audit the ledger", **extra}
    data = struct_pb2.Value()
    data.struct_value.update({"kind": "task", "payload": payload})
    message = Message(message_id="m1", parts=[Part(data=data, media_type=EVENT_MEDIA_TYPE)])
    envelope = EventEnvelope(kind="task", payload=payload)
    with pytest.raises(UnsupportedOperationError, match=next(iter(extra))):
        extension_from_envelope(envelope, message, "tiny-harness")


@pytest.mark.parametrize("extra", ATTEMPTS)
def test_an_envelope_on_an_existing_task_setting_one_is_refused_even_from_an_admin(
    extra: JsonObject,
) -> None:
    ext = TaskExtensionData(
        name="Refund",
        goal="g",
        participants=(Participant(id="ops", kind="human", role=Role.ADMIN),),
    )
    with pytest.raises(EnvelopeRefused, match="server-controlled"):
        apply_task_envelope(ext, {"name": "renamed", **extra}, actor="ops")
