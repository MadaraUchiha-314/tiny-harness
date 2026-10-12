"""Feature: Participant completion over the A2A server (critic round 1, B1 and B2)
Requirement: docs/specs/issue-25/requirements.md#R5

The control path skips the SDK's per-task queue: a duplicate control returns rather than
waiting for events that never come, and a non-streaming Complete answers with the state
the stream delivered.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from a2a.types import (
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskState,
)
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import make_server
from tests.integration.a2a.test_server import user_message
from tests.integration.durable.conftest import Harness, awaiting_next_message, close, env
from tests.integration.durable.test_complete import control, last_state
from tiny_harness.harness.commands import CommandInvokedIn, CommandResult, CommandSpec, SpawnIntent
from tiny_harness.harness.models import scripted
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]


def fork(ctx: CommandInvokedIn) -> CommandResult:
    return CommandResult(reply="", spawn=SpawnIntent(goal="look at the ledger"))


async def test_a_duplicate_control_returns_instead_of_waiting(env: WorkflowEnvironment) -> None:
    """
    Feature: Participant completion
    Scenario: the same control sent twice answers both times
        Given a parked conversation with an open sub-task, so completion is refused
        When the reporter sends the complete control, then sends it again (same message id)
        Then the second send returns within seconds with the task still INPUT_REQUIRED
    """
    suffix = uuid.uuid4().hex[:8]
    h = Harness([scripted("Refunded.")])
    h.commands.register(CommandSpec(name="fork", description="Fork"), fork)
    server = await make_server(env, [], task_queue=f"tq-{suffix}", harness=await h.bind())
    ctx = f"ctx-{suffix}"
    async with server:
        client = server.a2a()
        events = [
            e
            async for e in client.send_message(
                SendMessageRequest(message=user_message("hi", context_id=ctx))
            )
        ]
        tid = next(e.task.id for e in events if e.HasField("task"))
        handle = env.client.get_workflow_handle_for(TaskWorkflow.run, tid)
        await awaiting_next_message(handle)
        [
            e
            async for e in client.send_message(
                SendMessageRequest(message=user_message("/fork", context_id=ctx, task_id=tid))
            )
        ]
        again = control(task_id=tid, message_id="c-1", context_id=ctx)
        first = [e async for e in client.send_message(SendMessageRequest(message=again))]

        async def resend() -> list[StreamResponse]:
            return [e async for e in client.send_message(SendMessageRequest(message=again))]

        second = await asyncio.wait_for(resend(), timeout=10)
        await close(handle)
    assert last_state(first) == TaskState.TASK_STATE_INPUT_REQUIRED
    assert last_state(second) == TaskState.TASK_STATE_INPUT_REQUIRED


async def test_a_non_streaming_complete_answers_completed(env: WorkflowEnvironment) -> None:
    """
    Feature: Participant completion
    Scenario: SendMessage (not streaming) with the control returns the completed task
        Given a parked conversation
        When the reporter completes it over non-streaming SendMessage
        Then the returned task is COMPLETED, "completed by alice"
    """
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(env, [scripted("Refunded.")], task_queue=f"tq-{suffix}")
    ctx = f"ctx-{suffix}"
    async with server:
        tid = ""
        async for event in server.blocking().send_message(
            SendMessageRequest(
                message=user_message("refund 48213", context_id=ctx),
                configuration=SendMessageConfiguration(return_immediately=True),
            )
        ):
            if event.HasField("task"):
                tid = event.task.id
        await awaiting_next_message(env.client.get_workflow_handle_for(TaskWorkflow.run, tid))
        answers: list[Task] = [
            e.task
            async for e in server.blocking().send_message(
                SendMessageRequest(message=control(task_id=tid, context_id=ctx))
            )
            if e.HasField("task")
        ]
    assert answers and answers[-1].status.state == TaskState.TASK_STATE_COMPLETED
    assert answers[-1].status.message.parts[0].text == "completed by alice"
