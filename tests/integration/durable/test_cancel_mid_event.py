"""Feature: Cancelling a task
Requirement: docs/specs/issue-3/requirements.md#R15

A cancel that cuts a turn while one of its events is being delivered ends the task
CANCELED. Before, the delivery's cancelled activity escaped as an error and failed the
workflow, so the task never reached a state its parent's stand-in could hear (found in
issue-34, where stand-ins watch their children from the start).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from a2a.types import TaskState
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment

from tests.integration.durable.conftest import Harness, env, message, send, start, task
from tiny_harness.harness.models import scripted
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.models import EventEntry
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

ASK = ToolCall(
    call_id="a1",
    name="ask_participant",
    arguments={"participant_id": "alice", "question": "Which ledger?"},
)


class HeldSink:
    """Holds the delivery of the task's first INPUT_REQUIRED status until released."""

    def __init__(self) -> None:
        self.holding = asyncio.Event()
        self.release = asyncio.Event()

    async def deliver(self, task_id: str, context_id: str, entry: EventEntry) -> None:
        status = entry.payload.get("status")
        state = status.get("state") if isinstance(status, dict) else None
        if state == "TASK_STATE_INPUT_REQUIRED" and not self.holding.is_set():
            self.holding.set()
            await self.release.wait()


async def test_a_cancel_while_an_event_is_delivered_ends_the_task_canceled(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Cancelling a task
    Requirement: docs/specs/issue-3/requirements.md#R15

    Scenario: A cancel while an event is being delivered ends the task CANCELED
        Given a task whose model asks a participant, so the task parks
        And the delivery of its INPUT_REQUIRED status is held in flight
        When the task is cancelled
        Then the workflow ends CANCELED, not failed
    """
    sink = HeldSink()
    h = await Harness([scripted("", tool_calls=[ASK])]).bind()
    tid, tq = f"t-{uuid.uuid4().hex[:8]}", f"tq-{uuid.uuid4().hex[:8]}"
    async with h.worker(env.client, tq, sink=sink):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await asyncio.wait_for(sink.holding.wait(), timeout=30)
        await handle.signal(TaskWorkflow.cancel, "stopped by alice")
        try:
            result = await asyncio.wait_for(handle.result(), timeout=30)
        except WorkflowFailureError as exc:
            pytest.fail(f"the workflow failed instead of ending CANCELED: {exc.cause}")
        finally:
            sink.release.set()
    assert result.status.state == TaskState.TASK_STATE_CANCELED
