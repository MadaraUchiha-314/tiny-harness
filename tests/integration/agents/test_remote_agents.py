"""Feature: Remote agents
Requirement: docs/specs/issue-3/requirements.md#R7

Delegation to another A2A agent is a sub-task whose state follows the remote task.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from a2a.types import TaskState
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import env, make_server
from tests.integration.durable.conftest import Harness, message, send, start
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
        Then a remote task workflow sends the goal and follows the remote task to COMPLETED
        And the parent resumes with the remote answer and completes
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
            transport=httpx.ASGITransport(app=remote.app), base_url="http://harness"
        )
        agent = await RemoteAgent.connect("ledger", "http://harness", http=http)
        assert agent.agent_card.name == "tiny-harness"
        await local.registry.add(RegistryEntry(ref=agent.ref, instance=agent))
        async with local.worker(env.client, f"tq-l-{suffix}"):
            handle = await send(
                env.client, f"tq-l-{suffix}", start(), message("refund 48213", message_id="m1")
            )
            result = await handle.result()
            child = await env.client.get_workflow_handle("t-1.1").result()
        await agent.close()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert child.status.state == TaskState.TASK_STATE_COMPLETED
    ext = HarnessTask(result).ext
    assert [t.task_id for t in ext.sub_tasks] == ["t-1.1"]
    assert ext.sub_tasks[0].agent is not None and ext.sub_tasks[0].agent.id == "ledger"
    final_input = [i.text for i in local.llm.requests[-1].input if i.kind == "message"]
    assert any("Sub-task t-1.1 is COMPLETED: Ledger is balanced." in t for t in final_input)
    remote_records = await remote.harness.store.query(TaskRecord, Filter())
    assert any(r.state_name == "COMPLETED" for r in remote_records), "the remote ran its own task"
