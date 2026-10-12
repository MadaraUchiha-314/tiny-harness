"""The command-text parser (R6.1, R6.3, abuse case 9): a message is a command only when
its one part is text of the form ``/<name> <args>`` and the name is registered."""

from __future__ import annotations

import pytest
from a2a.types import Message, Part
from google.protobuf import struct_pb2

from tiny_harness.harness.commands import CommandCall, parse_command, parse_command_text

NAMES = frozenset({"model", "effort", "sub-task", "status"})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/status", CommandCall(name="status")),
        ("/model gpt-6-astra", CommandCall(name="model", arguments="gpt-6-astra")),
        (
            "/sub-task write the\nrelease notes",
            CommandCall(name="sub-task", arguments="write the\nrelease notes"),
        ),
        ("/effort   high", CommandCall(name="effort", arguments="high")),
    ],
)
def test_registered_commands_parse(text: str, expected: CommandCall) -> None:
    assert parse_command_text(text, NAMES) == expected


@pytest.mark.parametrize(
    "text",
    [
        "/unknown thing",  # R6.3: an unregistered name is an ordinary message
        "please /status",
        " /status",
        "/Status",
        "/9lives",
        "/models",
        "",
        "/",
    ],
)
def test_anything_else_is_an_ordinary_message(text: str) -> None:
    assert parse_command_text(text, NAMES) is None


def test_a_message_is_a_command_only_with_one_text_part() -> None:
    assert parse_command(Message(message_id="m", parts=[Part(text="/status")]), NAMES) == (
        CommandCall(name="status")
    )
    two = Message(message_id="m", parts=[Part(text="/status"), Part(text="and more")])
    assert parse_command(two, NAMES) is None
    data = struct_pb2.Value()
    data.struct_value.update({"x": 1})
    mixed = Message(message_id="m", parts=[Part(text="/status"), Part(data=data)])
    assert parse_command(mixed, NAMES) is None
    assert parse_command(Message(message_id="m", parts=[Part(data=data)]), NAMES) is None
