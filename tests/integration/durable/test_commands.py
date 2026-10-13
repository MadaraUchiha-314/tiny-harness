"""Feature: Slash commands
Requirement: docs/specs/issue-25/requirements.md#R6

A registered ``/<name>`` runs through the ``run_command`` activity and the
``command.invoked`` chain, never through the model. The workflow applies the command's
intents (settings, a sub-task) itself and replies on the task with its state unchanged.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from a2a.types import TaskState
from temporalio.testing import WorkflowEnvironment

from tests.integration.durable.conftest import (
    Harness,
    close,
    message,
    parked,
    send,
    start,
    task,
    until,
)
from tiny_harness.harness.commands import (
    BUILTIN_SPECS,
    CommandInvokedIn,
    CommandResult,
    CommandSpec,
    SpawnIntent,
    TaskSettings,
    exit_command,
)
from tiny_harness.harness.core import HarnessTask, Participant, Role, SubState, TaskExtensionData
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import TaskRecord
from tiny_harness.harness.tools import ToolCall
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.durable.models import EventEntry
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
GET_ORDER = ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})


def queue() -> str:
    return f"tq-{uuid.uuid4().hex[:8]}"


def task_id() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def replies(events: tuple[EventEntry, ...]) -> list[tuple[str, str, JsonObject]]:
    """Each command reply: the status state it rode on, its text and its metadata."""
    out: list[tuple[str, str, JsonObject]] = []
    for e in events:
        status = e.payload.get("status")
        if e.kind != "status_update" or not isinstance(status, dict):
            continue
        msg = status.get("message")
        if not isinstance(msg, dict):
            continue
        metadata = msg.get("metadata")
        if not isinstance(metadata, dict) or "command" not in metadata:
            continue
        parts = msg.get("parts")
        first = parts[0] if isinstance(parts, list) and parts else None
        text = first.get("text") if isinstance(first, dict) else None
        out.append((str(status.get("state")), str(text), metadata))
    return out


def with_status_command(h: Harness) -> list[CommandInvokedIn]:
    seen: list[CommandInvokedIn] = []

    def status(ctx: CommandInvokedIn) -> CommandResult:
        seen.append(ctx)
        return CommandResult(reply=f"{ctx.task.id} is {ctx.task.state} ({ctx.arguments})")

    h.commands.register(CommandSpec(name="status", description="Show the task"), status)
    return seen


async def test_a_command_runs_without_invoking_the_model_and_the_state_is_unchanged(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Slash commands
    Requirement: docs/specs/issue-25/requirements.md#R6

    Scenario: A command runs without invoking the model and the state is unchanged
        Given a conversation task awaiting the next message and a registered "/status"
        When the reporter sends "/status brief"
        Then the command's handler runs with the sender, its role and a snapshot of the task
        And its reply is on the task, tagged with the command's name
        And the model is not called and nothing joins the model's history
        And the task stays INPUT_REQUIRED awaiting the next message
    """
    h = await Harness([scripted("Refunded.")]).bind()
    seen = with_status_command(h)
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/status brief", task_id=tid, message_id="m2")
        )
        page = None
        for _ in range(400):
            page = await handle.query(TaskWorkflow.events_since, 0)
            if replies(page.events):
                break
            await asyncio.sleep(0.05)
        assert page is not None
        assert replies(page.events) == [
            ("TASK_STATE_INPUT_REQUIRED", f"{tid} is INPUT_REQUIRED (brief)", {"command": "status"})
        ]
        current = await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        assert current.state == TaskState.TASK_STATE_INPUT_REQUIRED
        assert len(h.llm.requests) == 1
        (ctx,) = seen
        assert (ctx.sender, ctx.sender_role, ctx.arguments) == ("alice", Role.REPORTER, "brief")
        assert ctx.task.sub_state is SubState.AWAITING_NEXT_MESSAGE
        await close(handle)


async def test_exit_marks_its_reply_for_the_sender_client_and_the_task_is_unchanged(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Slash commands
    Requirement: issue-32

    Scenario: The built-in /exit asks the sender's client to close
        Given a conversation task awaiting the next message and the built-in "/exit"
        When the reporter sends "/exit"
        Then the reply is tagged with the command's name and "close_client"
        And the model is not called
        And the task stays INPUT_REQUIRED awaiting the next message
    """
    h = await Harness([scripted("Refunded.")]).bind()
    h.commands.register(next(s for s in BUILTIN_SPECS if s.name == "exit"), exit_command)
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/exit", task_id=tid, message_id="m2")
        )
        page = None
        for _ in range(400):
            page = await handle.query(TaskWorkflow.events_since, 0)
            if replies(page.events):
                break
            await asyncio.sleep(0.05)
        assert page is not None
        assert replies(page.events) == [
            (
                "TASK_STATE_INPUT_REQUIRED",
                "Closing this client.",
                {"command": "exit", "close_client": "true"},
            )
        ]
        current = await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        assert current.state == TaskState.TASK_STATE_INPUT_REQUIRED
        assert len(h.llm.requests) == 1
        await close(handle)


async def test_a_command_sent_during_a_running_turn_replies_without_joining_the_history(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Slash commands
    Requirement: docs/specs/issue-25/requirements.md#R6

    Scenario: A command sent during a running turn replies without joining the history
        Given a turn whose tool call is still running
        When the reporter sends "/status"
        Then the command runs at the loop's next drain point and replies while WORKING
        And the model's next request does not contain the command's text
        And the turn ends as usual, awaiting the next message
    """
    h = await Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")]).bind()
    with_status_command(h)
    h.get_order.gate = asyncio.Event()
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await asyncio.wait_for(h.get_order.released.wait(), timeout=30)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/status", task_id=tid, message_id="m2")
        )
        h.get_order.gate.set()
        await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert replies(page.events) == [
            ("TASK_STATE_WORKING", f"{tid} is WORKING ()", {"command": "status"})
        ]
        await close(handle)
    assert len(h.llm.requests) == 2
    texts = [i.text for i in h.llm.requests[1].input if i.kind == "message"]
    assert not any("/status" in t for t in texts)


async def test_a_failing_command_replies_with_the_error_and_changes_nothing(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Slash commands
    Requirement: docs/specs/issue-25/requirements.md#R6

    Scenario: A failing command replies with the error and changes nothing
        Given a conversation task awaiting the next message
        And a registered "/explode" whose handler raises
        When the reporter sends "/explode"
        Then the reply is "/explode failed: boom"
        And the task's state, settings and history are as before, and the model is not called
    """

    def explode(ctx: CommandInvokedIn) -> CommandResult:
        raise RuntimeError("boom")

    h = await Harness([scripted("Refunded.")]).bind()
    h.commands.register(CommandSpec(name="explode", description="Fails"), explode)
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        before = await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/explode", task_id=tid, message_id="m2")
        )
        after = await until(
            handle,
            lambda t: t.proto.status.message.parts[0].text == "/explode failed: boom",
        )
        assert after.state == before.state and after.sub_state is before.sub_state
        assert after.ext == before.ext
        assert len(h.llm.requests) == 1
        await close(handle)


async def test_a_commands_settings_and_spawn_are_applied_by_the_workflow(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Slash commands
    Requirement: docs/specs/issue-25/requirements.md#R9

    Scenario: A command's intents are applied by the workflow, settings then spawn then reply
        Given a conversation task awaiting the next message
        And a command "/fork" that returns new settings and a sub-task to spawn
        When the reporter sends "/fork look at the ledger"
        Then the task's model and effort are the command's, persisted and published
        And a conversation sub-task exists, linked to the task, with the sender as reporter
        And the reply ends with "Created sub-task <id>." and carries the id as task_ref
    """

    def fork(ctx: CommandInvokedIn) -> CommandResult:
        return CommandResult(
            reply="Forking.",
            settings=TaskSettings(model="model-b", reasoning_effort="low"),
            spawn=SpawnIntent(goal=ctx.arguments),
        )

    h = await Harness([scripted("Refunded.")]).bind()
    h.commands.register(CommandSpec(name="fork", description="Fork"), fork)
    tq, tid = queue(), task_id()
    child_id = f"{tid}.1"
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/fork look at the ledger", task_id=tid, message_id="m2")
        )
        current = await until(
            handle, lambda t: t.proto.status.message.parts[0].text.startswith("Forking.")
        )
        assert current.proto.status.message.parts[0].text == (
            f"Forking.\nCreated sub-task {child_id}."
        )
        assert (current.ext.model, current.ext.reasoning_effort) == ("model-b", "low")
        assert [r.task_id for r in current.ext.sub_tasks] == [child_id]
        assert current.state == TaskState.TASK_STATE_INPUT_REQUIRED
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert replies(page.events)[-1][2] == {"command": "fork", "task_ref": child_id}
        record = await h.store.get(TaskRecord, tid)
        assert record is not None and HarnessTask(record.task).ext.model == "model-b"
        child = env.client.get_workflow_handle_for(TaskWorkflow.run, child_id)
        child_task = await until(child, parked(SubState.AWAITING_NEXT_MESSAGE))
        assert child_task.ext.goal == "look at the ledger"
        assert child_task.lifecycle == "conversation"
        assert (child_task.ext.model, child_task.ext.reasoning_effort) == ("model-b", "low")
        reporter = child_task.ext.participants[0]
        assert (reporter.id, reporter.role) == ("alice", Role.REPORTER)
        await close(handle)  # cancelling the parent cancels its open sub-task
        assert (await child.result()).status.state == TaskState.TASK_STATE_CANCELED
    assert len(h.llm.requests) == 1


async def test_a_participant_task_still_completes_on_the_assignees_answer_and_a_command_does_not(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Slash commands
    Requirement: docs/specs/issue-25/requirements.md#R3

    Scenario: A participant task still completes on the assignee's answer, and a command does not
        Given a task assigned to the participant "bob"
        When bob sends "/status"
        Then the command replies and the task stays INPUT_REQUIRED
        When bob sends an ordinary answer
        Then the task is COMPLETED with the answer
    """
    h = await Harness([]).bind()
    with_status_command(h)
    tq, tid = queue(), task_id()
    assigned = HarnessTask.new(
        tid,
        "ctx-1",
        TaskExtensionData(
            name="Approve",
            goal="Approve the refund?",
            participants=(
                Participant(id="agent", kind="agent", role=Role.REPORTER),
                Participant(id="bob", kind="human", role=Role.ASSIGNEE),
            ),
        ),
    )
    participant_start = start(assigned).model_copy(update={"mode": "participant"})
    async with h.worker(env.client, tq):
        handle = await env.client.start_workflow(
            TaskWorkflow.run, participant_start, id=tid, task_queue=tq
        )
        await until(handle, lambda t: t.state == TaskState.TASK_STATE_INPUT_REQUIRED)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox,
            message("/status", task_id=tid, message_id="m1", participant="bob"),
        )
        replied = await until(handle, lambda t: t.proto.status.message.parts[0].text.endswith("()"))
        assert replied.state == TaskState.TASK_STATE_INPUT_REQUIRED
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox,
            message("Approved.", task_id=tid, message_id="m2", participant="bob"),
        )
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert result.status.message.parts[0].text == "Approved."
