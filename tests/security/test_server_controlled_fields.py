"""Abuse case 1 (and its siblings): ``lifecycle``, ``model`` and ``reasoning_effort`` are
server-controlled; no participant's ``task`` envelope may set them (R3, R7.3)."""

from __future__ import annotations

from typing import cast

import pytest
from a2a.types import Message, Part
from a2a.utils.errors import UnsupportedOperationError
from google.protobuf import struct_pb2
from temporalio.client import Client

from tiny_harness.harness.core import Participant, Role, TaskExtensionData
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.bridge import EventBridge
from tiny_harness.service.a2a.executor import HarnessExecutor, extension_from_envelope
from tiny_harness.service.durable.models import WorkflowConfig
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


def brief(payload: JsonObject, sender: str) -> tuple[EventEnvelope, Message]:
    data = struct_pb2.Value()
    data.struct_value.update({"kind": "task", "payload": payload})
    message = Message(message_id="m1", parts=[Part(data=data, media_type=EVENT_MEDIA_TYPE)])
    message.metadata.update({"participant_id": sender})
    return EventEnvelope(kind="task", payload=payload), message


def test_a_trusted_delegator_may_brief_a_new_task_fully() -> None:
    """issue-34 R7: the harness itself (or a peer the operator trusts) creates a child that
    finishes by itself on the parent's settings; the fields are refused from anyone else."""
    payload: JsonObject = {
        "name": "Audit",
        "goal": "Audit the ledger",
        "lifecycle": "delegated",
        "model": "model-b",
        "reasoning_effort": "high",
    }
    envelope, message = brief(payload, "tiny-harness")
    ext = extension_from_envelope(envelope, message, "tiny-harness", trusted=True)
    assert (ext.lifecycle, ext.model, ext.reasoning_effort) == ("delegated", "model-b", "high")
    envelope, message = brief(payload, "alice")
    with pytest.raises(UnsupportedOperationError, match="server-controlled"):
        extension_from_envelope(envelope, message, "tiny-harness")


def test_the_executor_trusts_this_agent_and_the_configured_delegators_only() -> None:
    """issue-34 abuse case 5: the trust set is this agent plus ``[server] delegators``."""
    executor = HarnessExecutor(
        cast(Client, object()),
        task_queue="q",
        bridge=cast(EventBridge, object()),
        config=WorkflowConfig(agent="front-desk"),
        delegators=("ledger-peer",),
    )
    assert executor._delegators == frozenset({"front-desk", "ledger-peer"})  # pyright: ignore[reportPrivateUsage]
