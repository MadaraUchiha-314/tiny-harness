"""Feature: Sub-task lifecycle and settings
Requirement: docs/specs/issue-25/requirements.md#R7

A sub-task the agent spawns is delegated and completes when its loop ends; a /sub-task is
a conversation that waits for its first message. Every local child inherits the
parent's model and reasoning effort.
"""

from __future__ import annotations

import uuid

import pytest
from a2a.types import TaskState
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import self_hosted
from tests.integration.durable.conftest import (
    Harness,
    awaiting_next_message,
    close,
    message,
    send,
    start,
    task,
    until,
)
from tiny_harness.harness.core import HarnessTask, Participant, Role, SubState, TaskRef
from tiny_harness.harness.models import scripted
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.workflows import TaskWorkflow, child_extension

pytestmark = pytest.mark.asyncio(loop_scope="module")

SPAWN = ToolCall(
    call_id="c1", name="spawn_subtask", arguments={"name": "Check", "goal": "Check the ledger"}
)
CREATE = ToolCall(
    call_id="c2",
    name="create_task_for_participant",
    arguments={"participant_id": "alice", "name": "Approve", "goal": "Approve the refund"},
)


def ids() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return f"tq-{suffix}", f"t-{suffix}"


def configured(task_id: str) -> HarnessTask:
    """A conversation whose participant chose a model and an effort (R7.3, R8.3)."""
    base = task(task_id)
    return base.with_ext(
        base.ext.model_copy(update={"model": "model-b", "reasoning_effort": "high"})
    )


async def test_sub_tasks_inherit_the_parents_model_and_effort(env: WorkflowEnvironment) -> None:
    """
    Feature: Sub-task lifecycle and settings
    Requirement: docs/specs/issue-25/requirements.md#R7

    Scenario: Sub-tasks inherit the parent's model and effort
        Given a task whose model is model-b and whose effort is high
        When its model spawns a sub-task and creates a task for a participant
        Then the agent sub-task is delegated and carries model-b and high
        And it completes when its loop ends
        And the participant task carries neither, because it makes no model call
    """
    h = await Harness(
        [scripted("", tool_calls=[SPAWN, CREATE]), *(scripted("Ok.") for _ in range(5))]
    ).bind()
    tq, tid = ids()
    async with self_hosted(env, task_queue=tq, harness=h):
        handle = await send(
            env.client,
            tq,
            start(configured(tid)),
            message("refund 48213", task_id=tid, message_id="m1"),
        )
        current = await until(handle, lambda t: len(t.ext.sub_tasks) == 2)
        # The agent child is a task on this harness's own A2A server (issue-34 R7).
        row = current.ext.sub_tasks[0]
        agent_child = HarnessTask(await env.client.get_workflow_handle(row.task_id).result())
        participant_id = current.ext.sub_tasks[1].task_id  # alice's task, over A2A too
        participant = HarnessTask(
            await env.client.get_workflow_handle(participant_id).query(TaskWorkflow.task_query)
        )
        await env.client.get_workflow_handle(participant_id).signal(TaskWorkflow.cancel, "done")
        note = f"Sub-task {participant_id} is CANCELED"

        def settled(t: HarnessTask) -> bool:  # close the parent between turns, not mid-turn
            last = [i.text for i in h.llm.requests[-1].input if i.kind == "message"]
            return t.sub_state is SubState.AWAITING_NEXT_MESSAGE and any(note in x for x in last)

        await until(handle, settled)
        await close(handle)
    assert agent_child.state == TaskState.TASK_STATE_COMPLETED  # R3.4
    assert agent_child.ext.lifecycle == "delegated"
    assert (agent_child.ext.model, agent_child.ext.reasoning_effort) == ("model-b", "high")
    assert agent_child.ext.parent_tasks == (TaskRef(task_id=tid),)
    assert (participant.ext.model, participant.ext.reasoning_effort) == (None, None)


async def test_a_sub_task_extension_is_a_conversation_that_inherits_the_settings() -> None:
    """``/sub-task`` (R9.1, R9.2, R7.3): the extension the dispatcher's spawn builds."""
    parent = configured("t-9")
    participants = (
        Participant(id="alice", kind="human", role=Role.REPORTER),
        Participant(id="agent", kind="agent", role=Role.ASSIGNEE),
    )
    ext = child_extension(
        parent,
        name="Draft the reply",
        goal="Draft the reply",
        participants=participants,
        lifecycle="conversation",
        inherit=True,
    )
    assert ext.lifecycle == "conversation"
    assert (ext.model, ext.reasoning_effort) == ("model-b", "high")
    assert ext.parent_tasks == (TaskRef(task_id="t-9"),)
    assert ext.participants == participants
    plain = child_extension(
        parent, name="x", goal="x", participants=participants, lifecycle=None, inherit=False
    )
    assert (plain.model, plain.reasoning_effort, plain.lifecycle) == (None, None, None)


async def test_a_conversation_sub_task_waits_for_its_first_message(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Sub-task lifecycle and settings
    Requirement: docs/specs/issue-25/requirements.md#R9

    Scenario: A conversation sub-task with no first message waits for one
        Given a /sub-task child started without a first message
        Then it waits in INPUT_REQUIRED, awaiting the next message, without a model call
        When its reporter writes to it
        Then it runs a turn and parks again awaiting the next message
    """
    h = await Harness([scripted("Drafted.")]).bind()
    tq, tid = ids()
    parent = configured(tid)
    child = HarnessTask.new(
        f"{tid}.1",
        parent.context_id,
        child_extension(
            parent,
            name="Draft the reply",
            goal="Draft the reply",
            participants=(
                Participant(id="alice", kind="human", role=Role.REPORTER),
                Participant(id="agent", kind="agent", role=Role.ASSIGNEE),
            ),
            lifecycle="conversation",
            inherit=True,
        ),
    )
    async with h.worker(env.client, tq):
        handle = await env.client.start_workflow(
            TaskWorkflow.run, start(child), id=child.id, task_queue=tq
        )
        waiting = await awaiting_next_message(handle)
        assert waiting.sub_state is SubState.AWAITING_NEXT_MESSAGE
        assert h.llm.requests == []
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox,
            message("start with the apology", task_id=child.id, message_id="m1"),
        )
        replied = await until(
            handle,
            lambda t: (
                t.sub_state is SubState.AWAITING_NEXT_MESSAGE
                and [p.text for p in t.proto.status.message.parts] == ["Drafted."]
            ),
        )
        await close(handle)
    assert replied.state == TaskState.TASK_STATE_INPUT_REQUIRED
    assert len(h.llm.requests) == 1
