"""Feature: Conversation task lifecycle
Requirement: docs/specs/issue-25/requirements.md#R3

A task a participant starts is a conversation: a reply parks it in ``INPUT_REQUIRED``
with a sub-state instead of completing it, and the next message resumes the same task.
"""

from __future__ import annotations

import uuid

import pytest
from a2a.types import TaskState
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import self_hosted
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
from tiny_harness.harness.core import STATUS_EXT_KEY, HarnessTask, SubState
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import TaskRecord
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.models import EventEntry
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")


def queue() -> str:
    return f"tq-{uuid.uuid4().hex[:8]}"


def task_id() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def statuses(events: tuple[EventEntry, ...]) -> list[tuple[str, str | None]]:
    """Each status update's state and the status extension's sub-state, in order."""
    out: list[tuple[str, str | None]] = []
    for e in events:
        if e.kind != "status_update":
            continue
        status = e.payload.get("status")
        metadata = e.payload.get("metadata")
        state = status.get("state") if isinstance(status, dict) else None
        ext = metadata.get(STATUS_EXT_KEY) if isinstance(metadata, dict) else None
        sub = ext.get("sub_state") if isinstance(ext, dict) else None
        out.append((str(state), str(sub) if sub is not None else None))
    return out


async def test_a_reply_leaves_a_conversation_task_awaiting_the_next_message(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Conversation task lifecycle
    Requirement: docs/specs/issue-25/requirements.md#R3

    Scenario: A reply leaves a conversation task awaiting the next message
        Given a task started by a participant's message
        When the core loop ends a turn without a tool call
        Then the task is INPUT_REQUIRED with the sub-state awaiting-next-message, not COMPLETED
        And the sub-state is in the task's metadata and in the status update's metadata
        And the store holds the parked task with its sub-state
        And the workflow stays open for the next message
    """
    h = await Harness([scripted("Refunded.")]).bind()
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(task(tid)),
            message("refund 48213", task_id=tid, message_id="m1"),
        )
        current = await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        assert current.proto.status.message.parts[0].text == "Refunded."
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert not page.closed
        assert statuses(page.events) == [
            ("TASK_STATE_WORKING", None),
            ("TASK_STATE_INPUT_REQUIRED", "awaiting-next-message"),
        ]
        assert "TASK_STATE_COMPLETED" not in {s for s, _ in statuses(page.events)}
        record = await h.store.get(TaskRecord, tid)
        assert record is not None and record.state_name == "INPUT_REQUIRED"
        assert HarnessTask(record.task).sub_state is SubState.AWAITING_NEXT_MESSAGE
        assert len(h.llm.requests) == 1
        result = await close(handle)
    assert result.status.state == TaskState.TASK_STATE_CANCELED


async def test_the_next_message_resumes_the_same_task_and_clears_the_sub_state(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Conversation task lifecycle
    Requirement: docs/specs/issue-25/requirements.md#R3

    Scenario: The next message resumes the same task and clears the sub-state
        Given a conversation task awaiting the next message
        When the participant sends another message to the same task
        Then the task goes back to WORKING with no sub-state
        And the model sees the earlier exchange and the new message in one history
        And the task parks again awaiting the next message
    """
    h = await Harness([scripted("Refunded."), scripted("Receipt sent.")]).bind()
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(task(tid)),
            message("refund 48213", task_id=tid, message_id="m1"),
        )
        await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        receipt = await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("and the receipt?", task_id=tid, message_id="m2")
        )
        assert receipt.accepted
        current = await until(
            handle,
            lambda t: (
                parked(SubState.AWAITING_NEXT_MESSAGE)(t)
                and t.proto.status.message.parts[0].text == "Receipt sent."
            ),
        )
        assert current.id == tid
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert statuses(page.events) == [
            ("TASK_STATE_WORKING", None),
            ("TASK_STATE_INPUT_REQUIRED", "awaiting-next-message"),
            ("TASK_STATE_WORKING", None),  # leaving INPUT_REQUIRED clears the sub-state
            ("TASK_STATE_INPUT_REQUIRED", "awaiting-next-message"),
        ]
        texts = [i.text for i in h.llm.requests[1].input if i.kind == "message"]
        assert any("refund 48213" in t for t in texts)
        assert any("Refunded." in t for t in texts)
        assert any("and the receipt?" in t for t in texts)
        await close(handle)


async def test_a_refused_message_does_not_wake_a_parked_conversation(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Conversation task lifecycle
    Requirement: docs/specs/issue-25/requirements.md#R3

    Scenario: A refused message does not wake a parked conversation
        Given a conversation task awaiting the next message
        When a message intake refuses reaches the task
        Then the model is not called
        And the task stays INPUT_REQUIRED with the sub-state awaiting-next-message
    """
    h = await Harness([scripted("Refunded.")]).bind()
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(task(tid)),
            message("refund 48213", task_id=tid, message_id="m1"),
        )
        await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox,
            message("let me in", task_id=tid, message_id="m2", participant="mallory"),
        )
        current = await until(
            handle, lambda t: "not accepted" in t.proto.status.message.parts[0].text
        )
        assert current.state == TaskState.TASK_STATE_INPUT_REQUIRED
        assert current.sub_state is SubState.AWAITING_NEXT_MESSAGE
        assert len(h.llm.requests) == 1
        await close(handle)


async def test_ask_participant_parks_the_task_awaiting_an_answer(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Conversation task lifecycle
    Requirement: docs/specs/issue-25/requirements.md#R3

    Scenario: ask_participant parks the task awaiting an answer
        Given the model asks the reporter a question through ask_participant
        When the run ends
        Then the task is INPUT_REQUIRED with the sub-state awaiting-answer
        And the status update carries the same sub-state
        When the reporter answers
        Then the task resumes and, after the reply, parks awaiting the next message
    """
    ask = ToolCall(
        call_id="c1",
        name="ask_participant",
        arguments={"participant_id": "alice", "question": "Full or partial?"},
    )
    h = await Harness([scripted("", tool_calls=[ask]), scripted("Full refund issued.")]).bind()
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(task(tid)),
            message("refund 48213", task_id=tid, message_id="m1"),
        )
        await until(handle, parked(SubState.AWAITING_ANSWER))
        record = await h.store.get(TaskRecord, tid)
        assert record is not None and record.state_name == "INPUT_REQUIRED"
        assert HarnessTask(record.task).sub_state is SubState.AWAITING_ANSWER
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("Full.", task_id=tid, message_id="m2")
        )
        await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert statuses(page.events) == [
            ("TASK_STATE_WORKING", None),
            ("TASK_STATE_INPUT_REQUIRED", "awaiting-answer"),
            ("TASK_STATE_WORKING", None),
            ("TASK_STATE_INPUT_REQUIRED", "awaiting-next-message"),
        ]
        await close(handle)


async def test_a_delegated_sub_task_still_completes_when_its_loop_ends(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Conversation task lifecycle
    Requirement: docs/specs/issue-25/requirements.md#R3

    Scenario: A delegated sub-task still completes when its loop ends
        Given a conversation task whose model spawns a sub-task through spawn_subtask
        When the sub-task's core loop ends a turn without a tool call
        Then the sub-task is COMPLETED, as before
        And the parent hears of it and parks awaiting the next message
    """
    spawn = ToolCall(
        call_id="c1", name="spawn_subtask", arguments={"name": "Check", "goal": "Check the ledger"}
    )
    h = await Harness(
        [
            scripted("", tool_calls=[spawn]),
            scripted("Checking."),
            scripted("Checking."),
            scripted("All done."),
        ]
    ).bind()
    tq, tid = queue(), task_id()
    async with self_hosted(env, task_queue=tq, harness=h):
        handle = await send(
            env.client,
            tq,
            start(task(tid)),
            message("refund 48213", task_id=tid, message_id="m1"),
        )
        current = await until(handle, lambda t: bool(t.ext.sub_tasks))  # the child exists
        row = current.ext.sub_tasks[0]  # a task on this harness's own A2A server (R7)
        child = await env.client.get_workflow_handle(row.task_id).result()
        assert child.status.state == TaskState.TASK_STATE_COMPLETED
        assert HarnessTask(child).lifecycle == "delegated"
        note = f"Sub-task {row.task_id} is COMPLETED"

        def heard(t: HarnessTask) -> bool:
            last = [i.text for i in h.llm.requests[-1].input if i.kind == "message"]
            return parked(SubState.AWAITING_NEXT_MESSAGE)(t) and any(note in x for x in last)

        current = await until(handle, heard)
        assert [r.task_id for r in current.ext.sub_tasks] == [row.task_id]
        await close(handle)
