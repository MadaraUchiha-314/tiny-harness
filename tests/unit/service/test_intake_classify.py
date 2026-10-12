"""Feature: Intake classification
Requirement: docs/specs/issue-25/requirements.md#R6 (R5.1, R6.2, R6.3)

``intake`` sorts every accepted message into one of three: a registered ``/<name>``
command, a ``control`` envelope, or an ordinary message for the model. A command or a
control writes an audit row and adds nothing to the model's history.
"""

from __future__ import annotations

import pytest
from a2a.types import Message, Part
from a2a.types import Role as A2ARole
from google.protobuf import struct_pb2

from tiny_harness.harness.commands import CommandCall, CommandRegistry, CommandResult, CommandSpec
from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.harness.core.inprocess import InProcessOperations
from tiny_harness.harness.entities import Registry
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.models import FakeLLM
from tiny_harness.harness.persistence import InboxAuditRecord, SqliteStore
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.models import IntakeIn, IntakeOut
from tiny_harness.service.inbox import EVENT_MEDIA_TYPE, EventEnvelope, envelope_of


def a_task() -> HarnessTask:
    return HarnessTask.new(
        "t-1",
        "ctx-1",
        TaskExtensionData(
            name="Refund",
            goal="g",
            participants=(
                Participant(id="alice", kind="human", role=Role.REPORTER),
                Participant(id="wendy", kind="human", role=Role.WATCHER),
                Participant(id="agent", kind="agent", role=Role.ASSIGNEE),
            ),
        ),
    )


def text(body: str, *, message_id: str = "m1", sender: str = "alice") -> Message:
    msg = Message(message_id=message_id, role=A2ARole.ROLE_USER, parts=[Part(text=body)])
    msg.metadata.update({"participant_id": sender})
    return msg


def envelope(raw: JsonObject, *, message_id: str = "m1", sender: str = "alice") -> Message:
    value = struct_pb2.Value()
    value.struct_value.update(raw)
    msg = Message(
        message_id=message_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(data=value, media_type=EVENT_MEDIA_TYPE)],
    )
    msg.metadata.update({"participant_id": sender})
    return msg


async def activities() -> tuple[Activities, SqliteStore]:
    hooks = HookManager()
    store = SqliteStore(":memory:")
    engine = InProcessOperations(
        registry=Registry(), hooks=hooks, llm=FakeLLM([]), store=store, system_prompt="s"
    )
    await engine.bind()
    commands = CommandRegistry(hooks)
    commands.register(
        CommandSpec(name="status", description="Show the task"),
        lambda ctx: CommandResult(reply="ok"),
    )
    commands.freeze()
    return Activities(engine, commands=commands), store


async def intake(message: Message) -> tuple[IntakeOut, SqliteStore]:
    acts, store = await activities()
    out = await acts.intake(
        IntakeIn(task_id="t-1", correlation_id="c", task=a_task().proto, message=message)
    )
    return out, store


async def test_a_registered_command_is_classified_and_adds_no_history() -> None:
    """
    Scenario: A registered command is classified, audited and kept out of the history
        Given a task and a registered command "status"
        When a participant sends "/status  now"
        Then intake accepts it as the command call (status, "now") with no model text
        And an audit row records the message as accepted
    """
    out, store = await intake(text("/status  now"))
    assert out.accepted and out.command == CommandCall(name="status", arguments="now")
    assert out.control is None and out.text == ""
    audit = await store.get(InboxAuditRecord, "m1")
    assert audit is not None and audit.accepted and audit.participant_id == "alice"


async def test_an_unregistered_slash_name_is_an_ordinary_message() -> None:
    """
    Scenario: An unregistered /name is an ordinary message (R6.3, abuse case 9)
        Given a task with no command named "unknown"
        When a participant sends "/unknown hi"
        Then intake accepts it as ordinary text for the model and classifies nothing
    """
    out, _ = await intake(text("/unknown hi"))
    assert out.accepted and out.command is None and out.control is None
    assert out.text == "/unknown hi"


async def test_a_control_complete_is_classified_and_adds_no_history() -> None:
    """
    Scenario: A control envelope from a participant is classified (R5.1)
        Given a task and its reporter
        When the reporter sends the control envelope {"kind": "control", "action": "complete"}
        Then intake accepts it as control "complete" with no model text, and audits it
    """
    out, store = await intake(envelope({"kind": "control", "action": "complete"}))
    assert out.accepted and out.control == "complete" and out.command is None
    assert out.text == ""
    audit = await store.get(InboxAuditRecord, "m1")
    assert audit is not None and audit.accepted


@pytest.mark.parametrize(
    "raw",
    [
        {"kind": "control", "action": "explode"},
        {"kind": "control", "action": "complete", "payload": {}},
        {"kind": "control", "action": "complete", "force": True},
        {"kind": "control"},
        {"kind": "task", "action": "complete", "payload": {"name": "x"}},
        {"kind": "task"},
    ],
    ids=["unknown-action", "payload", "extra-field", "no-action", "action-on-task", "no-payload"],
)
async def test_a_malformed_control_envelope_is_refused(raw: JsonObject) -> None:
    """
    Scenario: A control envelope is closed (design § Security: extra="forbid")
        Given an envelope with an unknown action, an extra field, or a mixed shape
        When intake reads it
        Then the message is not accepted and the reason names the invalid envelope
    """
    out, _ = await intake(envelope(raw))
    assert not out.accepted and out.control is None
    assert "invalid event envelope" in out.reason


def test_the_control_envelope_parses_as_an_event_envelope() -> None:
    parsed = envelope_of(envelope({"kind": "control", "action": "complete"}))
    assert parsed == EventEnvelope(kind="control", action="complete")
    task_env = envelope_of(envelope({"kind": "task", "payload": {"name": "x"}}))
    assert task_env is not None and task_env.payload == {"name": "x"} and task_env.action is None
