"""Feature: Durable core loop
Requirement: docs/specs/issue-3/requirements.md#R19

The core loop runs as a Temporal workflow; every side effect is a recorded activity.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from a2a.types import TaskState
from temporalio.testing import WorkflowEnvironment

from tests.integration.durable.conftest import Harness, message, send, start
from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookPoint, Operation, Phase
from tiny_harness.harness.models import ToolResultItem, scripted
from tiny_harness.harness.persistence import CompactionStoreRecord, Filter, TaskRecord
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.models import ActivityRetriedPre
from tiny_harness.service.durable.worker import build_replayer
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")

GET_ORDER = ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})
REFUND = ToolCall(call_id="c2", name="orders.refund", arguments={"order_id": "48213"})


def queue() -> str:
    return f"tq-{uuid.uuid4().hex[:8]}"


async def test_a_task_runs_the_loop_to_completion_with_recorded_activity_results(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Durable core loop
    Requirement: docs/specs/issue-3/requirements.md#R19

    Scenario: a task runs the loop to completion with recorded activity results
        Given a worker with a scripted LLM that calls one tool then answers
        When a message is sent through update-with-start
        Then the workflow completes with the answer in the COMPLETED status
        And the event log holds the Task then each status update
        And the store holds the task record with its events
        And replaying the history invokes no activity again
    """
    h = await Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")]).bind()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("refund 48213", message_id="m1"))
        result = await handle.result()
        assert result.status.state == TaskState.TASK_STATE_COMPLETED
        assert result.status.message.parts[0].text == "Refunded."
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert [e.kind for e in page.events] == ["task", "status_update", "status_update"]
        assert page.closed
        assert [c.name for c in h.get_order.calls] == ["orders.get_order"]
        assert len(h.llm.requests) == 2
        record = await h.store.get(TaskRecord, "t-1")
        assert record is not None and record.state_name == "COMPLETED" and len(record.events) == 3
        history = await handle.fetch_history()
    await build_replayer().replay_workflow(history)
    assert len(h.llm.requests) == 2


async def test_a_worker_crash_mid_activity_resumes_without_a_second_llm_call(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Durable core loop
    Requirement: docs/specs/issue-3/requirements.md#R19

    Scenario: a worker crash mid-activity resumes without a second LLM call
        Given the tool activity's first attempt stops heartbeating, as a dead worker's would
        When the heartbeat timeout elapses
        Then Temporal fails the attempt and the workflow schedules the next one
        And the tool runs again while the LLM, whose response is in history, is not called again
    """
    h = await Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")]).bind()
    h.heartbeat_every = 3600.0  # the first attempt never heartbeats
    h.get_order.gate = asyncio.Event()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(heartbeat_timeout=timedelta(seconds=2)),
            message("refund 48213", message_id="m1"),
        )
        await asyncio.wait_for(h.get_order.released.wait(), timeout=30)
        assert len(h.llm.requests) == 1
        h.get_order.gate = None  # the next attempt runs through
        result = await handle.result()
        h.get_order.released.set()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert len(h.get_order.calls) == 2
    assert len(h.llm.requests) == 2
    history = await handle.fetch_history()
    timed_out = [
        e for e in history.events if e.HasField("activity_task_timed_out_event_attributes")
    ]
    assert len(timed_out) == 1


async def test_a_non_idempotent_tool_failure_is_not_retried(env: WorkflowEnvironment) -> None:
    """
    Feature: Durable core loop
    Requirement: docs/specs/issue-3/requirements.md#R19

    Scenario: a non-idempotent tool failure is not retried
        Given orders.refund is not idempotent and fails once
        When the LLM calls it
        Then it runs exactly once
        And the LLM receives a tool.not_retried error result
        And the activity.failed hook saw the failure
    """
    h = await Harness([scripted("", tool_calls=[REFUND]), scripted("Could not refund.")]).bind()
    h.refund.fail_times = 1
    seen: list[str] = []

    async def observe(point: HookPoint, ctx: HookContext) -> HookContext | None:
        seen.append(str(point))
        return None

    h.hooks.register(
        FunctionExecutor(
            "observe",
            observe,
            points=[HookPoint(operation=Operation.ACTIVITY_FAILED, phase=Phase.PRE)],
        )
    )
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("refund 48213", message_id="m1"))
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert len(h.refund.calls) == 1
    assert seen == ["activity.failed.pre"]
    second = h.llm.requests[1].input
    results = [i for i in second if isinstance(i, ToolResultItem)]
    assert results and results[0].result.is_error
    assert "tool.not_retried" in (results[0].result.content[0].text or "")


async def test_activity_failed_and_activity_retried_hooks_run_between_workflow_managed_attempts(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Durable core loop
    Requirement: docs/specs/issue-3/requirements.md#R19

    Scenario: activity.failed and activity.retried hooks run between workflow-managed attempts
        Given orders.get_order is idempotent and fails twice
        When the LLM calls it
        Then the attempts are failed, retried, failed, retried, success
        And the retried hook could rewrite the delay
    """
    h = await Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")]).bind()
    h.get_order.fail_times = 2
    seen: list[str] = []

    async def observe(point: HookPoint, ctx: HookContext) -> HookContext | None:
        seen.append(f"{point.operation.value}@{ctx.attempt}")
        if isinstance(ctx, ActivityRetriedPre):
            return ctx.model_copy(update={"next_delay": ctx.next_delay / 2})
        return None

    h.hooks.register(
        FunctionExecutor(
            "observe",
            observe,
            points=[
                HookPoint(operation=Operation.ACTIVITY_FAILED, phase=Phase.PRE),
                HookPoint(operation=Operation.ACTIVITY_RETRIED, phase=Phase.PRE),
            ],
        )
    )
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("refund 48213", message_id="m1"))
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert len(h.get_order.calls) == 3
    assert seen == [
        "activity.failed@1",
        "activity.retried@1",
        "activity.failed@2",
        "activity.retried@2",
    ]
    assert len(h.llm.requests) == 2


async def test_an_inbox_message_to_an_executing_task_is_drained_at_the_next_iteration(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Durable core loop
    Requirement: docs/specs/issue-3/requirements.md#R15

    Scenario: an inbox message to an executing task is drained at the next iteration
        Given a tool activity is running
        When a second message arrives through the inbox update
        Then the running step finishes first
        And the next LLM turn sees the second message in its input
    """
    h = await Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")]).bind()
    h.get_order.gate = asyncio.Event()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("refund 48213", message_id="m1"))
        await asyncio.wait_for(h.get_order.released.wait(), timeout=30)
        receipt = await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("also expedite it", message_id="m2")
        )
        assert receipt.accepted and receipt.state_name == "WORKING"
        h.get_order.gate.set()
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    texts = [i.text for i in h.llm.requests[1].input if i.kind == "message"]
    assert any("also expedite it" in t for t in texts)
    assert not any(
        "also expedite it" in i.text for i in h.llm.requests[0].input if i.kind == "message"
    )


async def test_compaction_runs_before_the_llm_call_when_the_first_message_is_over_budget(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Durable core loop
    Requirement: docs/specs/issue-3/requirements.md#R10

    Scenario: compaction runs before the LLM call when the first message is over budget
        Given a turn budget the first message exceeds
        When the task runs
        Then the compaction activity summarises before the first LLM turn
        And a compaction record is stored
    """
    h = await Harness(
        [scripted("summary of the long complaint"), scripted("Refunded.")], turn_budget_tokens=150
    ).bind()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("complaint " * 300, message_id="m1"))
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert "Exchange:" in h.llm.requests[0].input[0].text  # type: ignore[union-attr]
    records = await h.store.query(CompactionStoreRecord, Filter(task_id="t-1"))
    assert len(records) == 1


async def test_continue_as_new_carries_the_mailbox_event_log_and_pending_help_request(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Durable core loop
    Requirement: docs/specs/issue-3/requirements.md#R19

    Scenario: continue-as-new carries the mailbox, event log and pending help request
        Given a history bound the first turn exceeds
        When the task asks a participant and the reply arrives
        Then the workflow continues as new before draining the reply
        And the new run still serves the whole event log from sequence 0
        And the reply resumes the task to completion
    """
    ask = ToolCall(
        call_id="c1",
        name="ask_participant",
        arguments={"participant_id": "alice", "question": "Full or partial?"},
    )
    h = await Harness([scripted("", tool_calls=[ask]), scripted("Full refund issued.")]).bind()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(history_event_bound=30), message("refund 48213", message_id="m1")
        )

        async def waiting() -> bool:
            t = await handle.query(TaskWorkflow.task_query)
            return t.status.state == TaskState.TASK_STATE_INPUT_REQUIRED

        for _ in range(100):
            if await waiting():
                break
            await asyncio.sleep(0.1)
        assert await waiting()
        first_run = (await handle.describe()).run_id
        receipt = await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("Full.", message_id="m2")
        )
        assert receipt.accepted
        result = await handle.result()
        assert result.status.state == TaskState.TASK_STATE_COMPLETED
        last_run = (await handle.describe()).run_id
        assert last_run != first_run
        page = await handle.query(TaskWorkflow.events_since, 0)
    assert page.events[0].seq == 0 and page.events[0].kind == "task"
    kinds = [(e.kind, e.payload.get("status", {}).get("state")) for e in page.events]  # type: ignore[union-attr]
    assert ("status_update", "TASK_STATE_INPUT_REQUIRED") in kinds
    assert kinds[-1] == ("status_update", "TASK_STATE_COMPLETED")
    reply = [i.text for i in h.llm.requests[1].input if i.kind == "message"]
    assert any("Full." in t and "Full or partial?" in t for t in reply)


async def test_a_parent_waits_for_an_unresolved_sub_task_before_completing(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Durable core loop
    Requirement: docs/specs/issue-3/requirements.md#R8

    Scenario: a parent waits for an unresolved sub-task before completing
        Given the LLM spawns a sub-task then emits no tool call
        When the child workflow completes
        Then the parent resumes with the child's result and completes
    """
    spawn = ToolCall(
        call_id="c1", name="spawn_subtask", arguments={"name": "Check", "goal": "Check the ledger"}
    )
    h = await Harness(
        [
            scripted("", tool_calls=[spawn]),
            scripted("Waiting on the check."),
            scripted("Ledger checked."),
            scripted("All done."),
        ]
    ).bind()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("refund 48213", message_id="m1"))
        result = await handle.result()
        child = await env.client.get_workflow_handle("t-1.1").result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert result.status.message.parts[0].text == "All done."
    assert child.status.state == TaskState.TASK_STATE_COMPLETED
    final_input = [i.text for i in h.llm.requests[-1].input if i.kind == "message"]
    assert any("Sub-task t-1.1 is COMPLETED" in t for t in final_input)
