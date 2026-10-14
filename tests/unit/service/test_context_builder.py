"""The participant resolver (issue-36 R4.1-R4.3, abuse case 1): without a resolver the
``X-Participant-Id`` header names the participant, as before; with one, only the resolver
does, the header is ignored, and a message's own claim cannot stand in for it."""

from __future__ import annotations

import pytest
from a2a.server.context import ServerCallContext
from a2a.types import Message, Part, Role
from a2a.utils.errors import InternalError, InvalidParamsError
from starlette.requests import Request

from tiny_harness.service.a2a.app import HarnessContextBuilder
from tiny_harness.service.a2a.executor import sender_of
from tiny_harness.service.a2a.task_store import (
    PARTICIPANT_STATE_KEY,
    STRICT_STATE_KEY,
    asserted_participant,
)


def request(header: str | None = None) -> Request:
    headers = [(b"x-participant-id", header.encode())] if header else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def message(claimed: str | None = None) -> Message:
    msg = Message(message_id="m1", role=Role.ROLE_USER, parts=[Part(text="hi")])
    if claimed is not None:
        msg.metadata.update({"participant_id": claimed})
    return msg


def test_without_a_resolver_the_header_names_the_participant() -> None:
    context = HarnessContextBuilder().build(request("alice"))
    assert asserted_participant(context) == "alice"
    assert STRICT_STATE_KEY not in context.state


def test_with_a_resolver_the_header_is_ignored() -> None:
    context = HarnessContextBuilder(lambda r: "alice").build(request("admin"))
    assert asserted_participant(context) == "alice"


def test_a_resolver_answering_none_asserts_nobody() -> None:
    context = HarnessContextBuilder(lambda r: None).build(request("admin"))
    assert PARTICIPANT_STATE_KEY not in context.state
    assert context.state[STRICT_STATE_KEY] is True


def test_a_raising_resolver_fails_the_request() -> None:
    def broken(r: Request) -> str | None:
        raise RuntimeError("auth backend down")

    with pytest.raises(InternalError) as caught:
        HarnessContextBuilder(broken).build(request("alice"))
    assert "auth backend down" not in str(caught.value)


def test_in_strict_mode_a_message_claim_alone_is_refused() -> None:
    context = HarnessContextBuilder(lambda r: None).build(request())
    with pytest.raises(InvalidParamsError):
        sender_of(message("admin"), context)


def test_in_strict_mode_the_resolved_participant_is_the_sender() -> None:
    context = HarnessContextBuilder(lambda r: "alice").build(request("admin"))
    msg = message()
    assert sender_of(msg, context) == "alice"
    assert msg.metadata["participant_id"] == "alice"


def test_without_a_resolver_a_message_claim_still_stands_alone() -> None:
    """decision-003, unchanged: no header and no resolver, the message's own claim."""
    assert sender_of(message("bob"), ServerCallContext()) == "bob"
