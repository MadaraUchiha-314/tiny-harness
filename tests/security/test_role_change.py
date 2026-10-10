"""Abuse case 8: a participant's role changes only on an admin's say-so (R13.3)."""

from __future__ import annotations

from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.harness.core.intrinsics import TaskContext, apply_to_task, core_intrinsics
from tiny_harness.harness.tools import ToolCall, ToolResult, WorkflowCommand

CALL = ToolCall(
    call_id="c1",
    name="set_participant_role",
    arguments={"participant_id": "bob", "role": "admin"},
)


def task() -> HarnessTask:
    return HarnessTask.new(
        "t-1",
        "ctx-1",
        TaskExtensionData(
            name="n",
            goal="g",
            participants=(
                Participant(id="alice", kind="human", role=Role.ADMIN),
                Participant(id="bob", kind="human", role=Role.WATCHER),
            ),
        ),
    )


async def invoke(actor: str | None) -> ToolResult | WorkflowCommand:
    tools = {t.ref.id: t for t in core_intrinsics(TaskContext(task(), actor))}
    return await tools["set_participant_role"].invoke(CALL)


async def test_role_change_requires_admin() -> None:
    for actor in (None, "bob", "mallory"):
        out = await invoke(actor)
        assert isinstance(out, ToolResult), actor
        assert out.is_error
        assert "only an admin" in (out.content[0].text or "")
    out = await invoke("alice")
    assert isinstance(out, WorkflowCommand)
    assert out.kind == "set_role"
    updated = apply_to_task(task(), out)
    assert updated.ext.has_role("bob", Role.ADMIN)
