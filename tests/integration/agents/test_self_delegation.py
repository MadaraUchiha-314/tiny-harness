"""Feature: The harness delegates to itself through its own A2A interface
Requirement: docs/specs/issue-34/requirements.md#R7

``spawn_subtask`` with ``agent`` null names the agent ``self``: the child is created with
``SendMessage`` on this harness's own A2A server, followed by the stand-in, and its answer
comes back to the parent like any remote agent's.
"""

from __future__ import annotations

import uuid

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import self_hosted
from tests.integration.durable.conftest import (
    Harness,
    close,
    env,
    message,
    parked,
    send,
    start,
    task,
    until,
)
from tests.integration.routed_llm import RoutedLLM, texts
from tiny_harness.harness.core import HarnessTask, SubState
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import Filter, TaskRecord
from tiny_harness.harness.tools import ToolCall

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

SECRET = "the parent's private working notes: customer alice, ticket 7"
GOAL = "Summarise the refund policy for damaged items"
DESCRIPTION = "The customer is in the EU; the policy book is the policy tool."
CRITERION = "Names the refund window in days"
RESULT = "Damaged items: full refund within 30 days. " + "Detail. " * 300  # 2,443 chars


async def test_a_sub_task_on_itself_goes_through_its_own_a2a_interface(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: The harness delegates to itself through its own A2A interface
    Requirement: docs/specs/issue-34/requirements.md#R7

    Scenario: A sub-task on itself goes through its own A2A interface and returns its result
        Given a harness that serves its own A2A app, registered as the agent "self"
        And a conversation whose history holds the parent's private notes
        When the model calls spawn_subtask with agent null, a goal, a description and a criterion
        Then a new A2A task is created on the harness's own server with that brief
        And the parent's sub-task row names that task, on this harness
        And the child's model input holds its goal, description and criterion
        And none of the parent's history
        And the parent's next model input holds the child's whole answer, as untrusted data
    """
    spawn = ToolCall(
        call_id="c1",
        name="spawn_subtask",
        arguments={
            "name": "Refund policy",
            "goal": GOAL,
            "description": DESCRIPTION,
            "acceptance_criteria": [CRITERION],
        },
    )
    llm = RoutedLLM(
        parent=[scripted("", tool_calls=[spawn]), scripted("Waiting for the policy.")],
        child=[scripted(RESULT)],
        child_goal=GOAL,
        parent_message=SECRET,
    )
    h = await Harness([]).bind()
    h.llm = h.engine.llm = llm
    suffix = uuid.uuid4().hex[:8]
    tid, tq = f"t-{suffix}", f"tq-self-{suffix}"
    async with self_hosted(env, task_queue=tq, harness=h):
        handle = await send(
            env.client, tq, start(task(tid)), message(SECRET, task_id=tid, message_id="m1")
        )
        current = await until(handle, lambda t: bool(t.ext.sub_tasks))
        (row,) = current.ext.sub_tasks
        assert row.agent is None  # on this harness, which surfaces open as their own
        assert row.task_id != tid and not row.task_id.startswith(f"{tid}.")

        def heard(t: HarnessTask) -> bool:
            mine = [r for r in llm.requests if not llm.is_child(r)]
            return parked(SubState.AWAITING_NEXT_MESSAGE)(t) and RESULT.strip() in texts(mine[-1])

        await until(handle, heard)
        records = {r.task_id: r for r in await h.store.query(TaskRecord, Filter())}
        child = HarnessTask(records[row.task_id].task)
        assert (child.ext.name, child.ext.description) == ("Refund policy", DESCRIPTION)
        assert [c.text for c in child.ext.acceptance_criteria] == [CRITERION]

        first_child = next(r for r in llm.requests if llm.is_child(r))
        seen = texts(first_child)
        for part in (GOAL, DESCRIPTION, CRITERION):
            assert part in seen, part
        assert "alice" not in seen and "ticket 7" not in seen

        last = texts([r for r in llm.requests if not llm.is_child(r)][-1])
        assert '<untrusted source="agent">' in last and RESULT.strip() in last
        await close(handle)
