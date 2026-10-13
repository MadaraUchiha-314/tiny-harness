"""Feature: Remote agents
Requirement: docs/specs/issue-3/requirements.md#R7

Delegation to another A2A agent is a sub-task whose state follows the remote task.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from a2a.types import TaskState
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import env, make_server
from tests.integration.durable.conftest import (
    Harness,
    awaiting_next_message,
    close,
    message,
    send,
    start,
    until,
)
from tests.integration.streaming_asgi import StreamingASGITransport
from tiny_harness.harness.agents import RemoteAgent
from tiny_harness.harness.core import HarnessTask
from tiny_harness.harness.entities import RegistryEntry
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import Filter, TaskRecord
from tiny_harness.harness.tools import ToolCall

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

DELEGATE = ToolCall(
    call_id="c1",
    name="spawn_subtask",
    arguments={
        "name": "Ledger check",
        "goal": "Check the ledger for order 48213",
        "agent": "ledger",
    },
)


async def test_delegation_to_a_remote_a2a_agent_tracks_the_sub_task_state(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Remote agents
    Requirement: docs/specs/issue-3/requirements.md#R7

    Scenario: delegation to a remote A2A agent tracks the sub-task state
        Given a second harness serving A2A as the "ledger" agent, registered from its card
        When the local LLM spawns a sub-task on that agent
        Then the goal is sent and a stand-in follows the remote task to its answer
        And the remote parks its own task awaiting the next message (issue-25 R3.1)
        And the local sub-task completes with that answer (issue-25 R3.4)
        And the parent resumes with the remote answer and parks awaiting the next message
    """
    suffix = uuid.uuid4().hex[:8]
    remote = await make_server(env, [scripted("Ledger is balanced.")], task_queue=f"tq-r-{suffix}")
    local = await Harness(
        [
            scripted("", tool_calls=[DELEGATE]),
            scripted("Waiting on the ledger."),
            scripted("All done."),
        ]
    ).bind()
    async with remote:
        http = httpx.AsyncClient(
            transport=StreamingASGITransport(remote.app), base_url="http://harness"
        )
        agent = await RemoteAgent.connect("ledger", "http://harness", http=http)
        assert agent.agent_card.name == "tiny-harness"
        await local.registry.add(RegistryEntry(ref=agent.ref, instance=agent))
        async with local.worker(env.client, f"tq-l-{suffix}"):
            handle = await send(
                env.client, f"tq-l-{suffix}", start(), message("refund 48213", message_id="m1")
            )
            current = await until(handle, lambda t: bool(t.ext.sub_tasks))  # child created
            # The row names the child's own task on the agent (issue-34 R7.4); the stand-in
            # that follows it is this task's workflow ``t-1.1``.
            remote_id = current.ext.sub_tasks[0].task_id
            child = await env.client.get_workflow_handle("t-1.1").result()
            note = f"Sub-task {remote_id} is COMPLETED: Ledger is balanced."

            async def heard() -> HarnessTask:
                for _ in range(200):
                    parked = await awaiting_next_message(handle)
                    last = local.llm.requests[-1].input
                    if any(note in i.text for i in last if i.kind == "message"):
                        return parked
                    await asyncio.sleep(0.05)
                raise AssertionError("the parent never heard of its sub-task")

            result = (await heard()).proto
            await close(handle)
        await agent.close()
    assert result.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    assert child.status.state == TaskState.TASK_STATE_COMPLETED
    ext = HarnessTask(result).ext
    assert [t.task_id for t in ext.sub_tasks] == [remote_id]
    assert ext.sub_tasks[0].agent is not None and ext.sub_tasks[0].agent.id == "ledger"
    final_input = [i.text for i in local.llm.requests[-1].input if i.kind == "message"]
    assert any(note in t for t in final_input)
    remote_records = {r.task_id: r for r in await remote.harness.store.query(TaskRecord, Filter())}
    assert remote_records[remote_id].state_name == "INPUT_REQUIRED", "the remote ran its task"
