"""A child's signal that reaches a continued run before ``run`` loads it (issue-34).

A signal handler can run in a run's first activation, before ``run`` restores the
children from the snapshot. The child's change must not be lost to the load: before, the
row stayed unresolved and the note named the stand-in's workflow, not the child's task.
"""

from __future__ import annotations

from a2a.types import Task

from tiny_harness.harness.core import AgentState
from tiny_harness.service.durable.models import ChildDone, ChildRef, TaskStart
from tiny_harness.service.durable.workflows import TaskWorkflow


def snapshot() -> TaskStart:
    child = ChildRef(task_id="remote-9", workflow_id="t-1.1", kind="agent", state_name="WORKING")
    return TaskStart(
        task=Task(id="t-1"),
        state=AgentState(task_id="t-1"),
        correlation_id="t-1",
        children=(child,),
    )


async def test_a_child_done_before_the_load_is_applied_after_it() -> None:
    wf = TaskWorkflow()
    await wf.child_done(ChildDone(task_id="t-1.1", state_name="CANCELED", summary="stopped"))
    wf._load(snapshot())  # pyright: ignore[reportPrivateUsage]
    (child,) = wf.children
    assert (child.done, child.state_name) == (True, "CANCELED")
    assert wf.notes == ["Sub-task remote-9 is CANCELED: stopped"]


async def test_a_child_done_after_the_load_is_applied_at_once() -> None:
    wf = TaskWorkflow()
    wf._load(snapshot())  # pyright: ignore[reportPrivateUsage]
    await wf.child_done(ChildDone(task_id="t-1.1", state_name="COMPLETED", summary="done"))
    assert wf.children[0].done
    assert wf.notes == ["Sub-task remote-9 is COMPLETED: done"]
