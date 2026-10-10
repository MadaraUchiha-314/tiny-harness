"""The A2A server's pure parts (R14.2-R14.4, R15.1, abuse cases 6 and 7)."""

from __future__ import annotations

import pytest
from a2a.types import Message, Part
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
from google.protobuf import struct_pb2

from tiny_harness.harness.channels import CHANNEL_EXT_URI
from tiny_harness.harness.core import TASK_EXT_URI, Role
from tiny_harness.harness.security import MASK, Redactor
from tiny_harness.service.a2a.card import (
    A2UI_EXT_URI,
    EVENT_MEDIA_TYPE,
    SUPPORTED_EXTENSIONS,
    AgentDescription,
    build_agent_card,
)
from tiny_harness.service.a2a.executor import (
    HarnessExecutor,
    default_extension,
    envelope_of,
    extension_from_envelope,
    redact_message,
)
from tiny_harness.service.a2a.middleware import TokenBucket


def test_the_card_advertises_every_extension_and_no_security_scheme() -> None:
    card = build_agent_card(AgentDescription(), "http://127.0.0.1:8080")
    uris = {e.uri for e in card.capabilities.extensions}
    assert uris == {TASK_EXT_URI, CHANNEL_EXT_URI, A2UI_EXT_URI} == set(SUPPORTED_EXTENSIONS)
    assert all(not e.required for e in card.capabilities.extensions)
    assert {i.protocol_binding for i in card.supported_interfaces} == {"JSONRPC", "HTTP+JSON"}
    assert all(i.protocol_version == "1.0" for i in card.supported_interfaces)
    assert card.capabilities.streaming and card.capabilities.push_notifications
    assert not card.security_schemes and not card.security_requirements


def test_unadvertised_extensions_are_refused_before_intake() -> None:
    executor = HarnessExecutor.__new__(HarnessExecutor)
    executor.check_extensions({TASK_EXT_URI})
    with pytest.raises(UnsupportedOperationError):
        executor.check_extensions({TASK_EXT_URI, "https://example.com/ext/evil/v1"})


def test_ingress_redaction_covers_text_and_data_parts() -> None:
    value = struct_pb2.Value()
    value.struct_value.update({"note": "token=abcdefghijklmnop", "nested": ["sk-abcdefghijklmnop"]})
    message = Message(
        message_id="m1",
        parts=[Part(text="Bearer abcdefghijklmnop please"), Part(data=value, media_type="x")],
    )
    clean = redact_message(Redactor(), message)
    assert clean.parts[0].text == f"{MASK} please"
    data = clean.parts[1].data.struct_value
    assert data["note"] == f"token={MASK}"
    assert data["nested"][0] == MASK  # type: ignore[index]
    assert message.parts[0].text.startswith("Bearer")  # the original is untouched


def test_ingress_redaction_covers_message_and_part_metadata() -> None:
    message = Message(message_id="m2", parts=[Part(text="hello")])
    message.metadata.update({"participant_id": "alice", "api_key": "sk-abcdefghijklmnop"})
    message.parts[0].metadata.update({"trace": "Bearer abcdefghijklmnop"})
    clean = redact_message(Redactor(), message)
    assert clean.metadata["participant_id"] == "alice"
    assert clean.metadata["api_key"] == MASK
    assert clean.parts[0].metadata["trace"] == MASK
    assert clean.parts[0].text == "hello" and clean.message_id == "m2"


def test_default_extension_names_the_reporter_and_the_agent() -> None:
    message = Message(message_id="m1", parts=[Part(text="Refund order 48213\nIt was late")])
    message.metadata.update({"participant_id": "alice"})
    ext = default_extension(message, "tiny-harness")
    assert ext.name == "Refund order 48213"
    assert ext.goal.startswith("Refund order 48213")
    assert [(p.id, p.role) for p in ext.participants] == [
        ("alice", Role.REPORTER),
        ("tiny-harness", Role.ASSIGNEE),
    ]


def test_event_envelope_task_payload_becomes_the_extension_and_invalid_ones_are_rejected() -> None:
    good = struct_pb2.Value()
    good.struct_value.update(
        {"kind": "task", "payload": {"name": "Audit", "goal": "Audit the ledger"}}
    )
    message = Message(message_id="m1", parts=[Part(data=good, media_type=EVENT_MEDIA_TYPE)])
    envelope = envelope_of(message)
    assert envelope is not None and envelope.kind == "task"
    ext = extension_from_envelope(envelope, message, "tiny-harness")
    assert ext.name == "Audit" and ext.participants[0].role is Role.ASSIGNEE
    bad = struct_pb2.Value()
    bad.struct_value.update({"kind": "bogus", "payload": {}})
    with pytest.raises(InvalidParamsError):
        envelope_of(Message(message_id="m2", parts=[Part(data=bad, media_type=EVENT_MEDIA_TYPE)]))
    worse = struct_pb2.Value()
    worse.struct_value.update({"kind": "task", "payload": {"name": "x", "unknown": 1}})
    env2 = envelope_of(
        Message(message_id="m3", parts=[Part(data=worse, media_type=EVENT_MEDIA_TYPE)])
    )
    assert env2 is not None
    with pytest.raises(InvalidParamsError):
        extension_from_envelope(env2, message, "tiny-harness")


def test_token_bucket_refills_at_the_configured_rate() -> None:
    bucket = TokenBucket(60)  # one per second, capacity 60
    assert all(bucket.take("peer", now=0.0) for _ in range(60))
    assert not bucket.take("peer", now=0.0)
    assert bucket.take("peer", now=1.0)
    assert bucket.take("other", now=0.0)
