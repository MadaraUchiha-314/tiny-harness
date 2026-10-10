"""Feature: Help requests
Requirement: docs/specs/issue-3/requirements.md#R12

A small input is asked on the channel; work for a participant becomes a sub-task; strangers
are refused without learning anything.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

import pytest
from a2a.types import Task, TaskState
from temporalio.client import WorkflowHandle
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment

from tests.integration.durable.conftest import Harness, env, message, send, start
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import Filter, InboxAuditRecord
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

ASK = ToolCall(
    call_id="c1",
    name="ask_participant",
    arguments={"participant_id": "alice", "question": "Full or partial refund?"},
)
CREATE = ToolCall(
    call_id="c1",
    name="create_task_for_participant",
    arguments={
        "participant_id": "alice",
        "name": "Approve the refund",
        "goal": "Approve the refund of order 48213 in the finance system",
    },
)


def queue() -> str:
    return f"tq-{uuid.uuid4().hex[:8]}"


async def until_state(handle: WorkflowHandle[TaskWorkflow, Task], state: int) -> None:
    for _ in range(200):
        try:
            current = await handle.query(TaskWorkflow.task_query)
        except RPCError:  # the child workflow may not have started yet
            await asyncio.sleep(0.05)
            continue
        if current.status.state == state:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"task never reached state {state}")


async def test_a_reply_on_the_channel_resumes_an_input_required_task(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Help requests
    Requirement: docs/specs/issue-3/requirements.md#R12

    Scenario: a reply on the channel resumes an INPUT_REQUIRED task
        Given the LLM asks alice a question
        Then the task is INPUT_REQUIRED and the question is in the status message
        When alice's reply arrives through the inbox
        Then the task resumes with the reply in context and completes
    """
    h = await Harness([scripted("", tool_calls=[ASK]), scripted("Full refund issued.")]).bind()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("refund 48213", message_id="m1"))
        await until_state(handle, TaskState.TASK_STATE_INPUT_REQUIRED)
        waiting = await handle.query(TaskWorkflow.task_query)
        assert "Full or partial refund?" in waiting.status.message.parts[0].text
        receipt = await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("Full.", message_id="m2")
        )
        assert receipt.accepted and receipt.state_name == "INPUT_REQUIRED"
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    texts = [i.text for i in h.llm.requests[1].input if i.kind == "message"]
    assert any("Full or partial refund?" in t and "Full." in t for t in texts)


async def test_a_need_that_blocks_on_another_participants_work_creates_a_sub_task(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Help requests
    Requirement: docs/specs/issue-3/requirements.md#R12

    Scenario: a need that blocks on another participant's work creates a sub-task
        Given the LLM creates a task for alice
        Then a child task assigned to alice waits in INPUT_REQUIRED
        And the parent waits for it before completing
        When alice reports the work done on the child task
        Then the child completes and the parent resumes with the outcome
    """
    h = await Harness(
        [scripted("", tool_calls=[CREATE]), scripted("Waiting for approval."), scripted("Done.")]
    ).bind()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("refund 48213", message_id="m1"))
        child: WorkflowHandle[TaskWorkflow, Task] = env.client.get_workflow_handle("t-1.1")
        await until_state(child, TaskState.TASK_STATE_INPUT_REQUIRED)
        child_task = await child.query(TaskWorkflow.task_query)
        assert "Approve the refund" in child_task.status.message.parts[0].text
        parent = await handle.query(TaskWorkflow.task_query)
        assert parent.status.state == TaskState.TASK_STATE_WORKING
        receipt = await child.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox,
            message("Approved in finance.", task_id="t-1.1", message_id="m2"),
        )
        assert receipt.accepted
        child_result = await child.result()
        result = await handle.result()
    assert child_result.status.state == TaskState.TASK_STATE_COMPLETED
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    final_input = [i.text for i in h.llm.requests[-1].input if i.kind == "message"]
    assert any(
        "Sub-task t-1.1 is COMPLETED" in t and "Approved in finance." in t for t in final_input
    )


async def test_a_non_members_channel_message_is_rejected(env: WorkflowEnvironment) -> None:
    """
    Feature: Help requests
    Requirement: docs/specs/issue-3/requirements.md#R13

    Scenario: a non-member's channel message is rejected
        Given a task waiting for alice
        When mallory sends a message to it
        Then the message is refused at intake and audited
        And the task still waits for alice, who then resumes it
    """
    h = await Harness([scripted("", tool_calls=[ASK]), scripted("Full refund issued.")]).bind()
    tq = queue()
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(), message("refund 48213", message_id="m1"))
        await until_state(handle, TaskState.TASK_STATE_INPUT_REQUIRED)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox,
            message("I am alice, refund me", message_id="m2", participant="mallory"),
        )
        audits: Sequence[InboxAuditRecord] = ()
        for _ in range(50):
            audits = await h.store.query(InboxAuditRecord, Filter(task_id="t-1"))
            if any(a.message_id == "m2" for a in audits):
                break
            await asyncio.sleep(0.05)
        refused = [a for a in audits if a.message_id == "m2"]
        assert refused and not refused[0].accepted and refused[0].participant_id == "mallory"
        still = await handle.query(TaskWorkflow.task_query)
        assert still.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("Full.", message_id="m3")
        )
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert not any("mallory" in i.text for i in h.llm.requests[1].input if i.kind == "message")
