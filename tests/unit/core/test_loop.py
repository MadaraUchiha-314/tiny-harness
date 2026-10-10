"""The core loop over the in-process host (R8.4, R8.5, R9.2, R12.2, decision-004)."""

from __future__ import annotations

from a2a.types import TaskState

from tiny_harness.harness.core import (
    AgentState,
    HarnessTask,
    Participant,
    Role,
    StepState,
    TaskExtensionData,
)
from tiny_harness.harness.core.inprocess import TASK_COMPLETE, InProcessOperations
from tiny_harness.harness.core.loop import CompletionDecision, CoreLoop, TaskCompleteIn
from tiny_harness.harness.entities import Registry
from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookManager, HookPoint
from tiny_harness.harness.models import FakeLLM, LLMResponse, ToolResultItem, scripted
from tiny_harness.harness.persistence import PlanRecord, SqliteStore, StateRecord, TaskRecord
from tiny_harness.harness.tools import ToolCall

PLAN_CALL = ToolCall(
    call_id="c1",
    name="create_plan",
    arguments={
        "steps": [
            {"name": "Gather facts", "description": "Read the order"},
            {"name": "Decide", "description": "Refund or not", "depends_on": ["Gather facts"]},
        ]
    },
)


def task() -> HarnessTask:
    return HarnessTask.new(
        "t-1",
        "ctx-1",
        TaskExtensionData(
            name="Refund",
            goal="Resolve the complaint",
            participants=(
                Participant(id="alice", kind="human", role=Role.REPORTER),
                Participant(id="agent", kind="agent", role=Role.ASSIGNEE),
            ),
        ),
    )


async def host(*responses: LLMResponse) -> tuple[InProcessOperations, FakeLLM]:
    llm = FakeLLM(list(responses))
    ops = InProcessOperations(
        registry=Registry(),
        hooks=HookManager(),
        llm=llm,
        store=SqliteStore(":memory:"),
        system_prompt="You are the harness.",
    )
    await ops.bind()
    return ops, llm


async def test_loop_terminates_when_the_llm_emits_no_tool_call() -> None:
    ops, llm = await host(scripted("All done."))
    out = await CoreLoop(ops).run(task(), AgentState(task_id="t-1"), "Please refund order 42")
    assert out.kind == "completed"
    assert out.final_text == "All done."
    assert out.task.state == TaskState.TASK_STATE_COMPLETED
    assert out.state.turn == 1
    request = llm.requests[0]
    assert [i.kind for i in request.input] == ["message", "message"]
    assert {t.name for t in request.tools} >= {"create_plan", "ask_participant", "emit_ui"}
    assert await ops.store.get(TaskRecord, "t-1") is not None
    assert await ops.store.get(StateRecord, "t-1:1") is not None


async def test_create_plan_attaches_the_plan_and_complete_step_marks_it_done() -> None:
    ops, _ = await host(
        scripted("", tool_calls=[PLAN_CALL]),
        scripted(
            "",
            tool_calls=[
                ToolCall(
                    call_id="c2",
                    name="complete_step",
                    arguments={"step": "Gather facts", "output": "Order 42 was late"},
                )
            ],
        ),
        scripted("Refunded."),
    )
    out = await CoreLoop(ops).run(task(), AgentState(task_id="t-1"), "go")
    assert out.kind == "completed"
    plan = out.task.ext.plan
    assert plan is not None
    assert [s.id for s in plan.steps] == ["gather-facts", "decide"]
    assert plan.step("gather-facts").state is StepState.DONE
    assert plan.step("gather-facts").output == "Order 42 was late"
    assert plan.step("decide").depends_on == ("gather-facts",)
    assert await ops.store.get(PlanRecord, "t-1:1") is not None
    kinds = [e.item.kind for e in out.state.history]
    assert kinds == ["message", "tool_call", "tool_result", "tool_call", "tool_result", "message"]


async def test_ask_participant_moves_the_task_to_input_required_and_a_reply_resumes() -> None:
    ops, _ = await host(
        scripted(
            "",
            tool_calls=[
                ToolCall(
                    call_id="c1",
                    name="ask_participant",
                    arguments={"participant_id": "alice", "question": "Full or partial refund?"},
                )
            ],
        ),
        scripted("Full refund issued."),
    )
    loop = CoreLoop(ops)
    first = await loop.run(task(), AgentState(task_id="t-1"), "go")
    assert first.kind == "waiting_for_reply"
    assert first.task.state == TaskState.TASK_STATE_INPUT_REQUIRED
    assert first.help is not None
    assert first.help["participant_id"] == "alice"
    assert first.help["question"] == "Full or partial refund?"
    second = await loop.run(first.task, first.state, "Full.")
    assert second.kind == "completed"
    assert second.task.state == TaskState.TASK_STATE_COMPLETED
    assert [e.item.kind for e in second.state.history][-2:] == ["message", "message"]


async def test_asking_a_stranger_is_refused_without_leaking_membership() -> None:
    ops, _ = await host(
        scripted(
            "",
            tool_calls=[
                ToolCall(
                    call_id="c1",
                    name="ask_participant",
                    arguments={"participant_id": "mallory", "question": "hi?"},
                )
            ],
        ),
        scripted("ok"),
    )
    out = await CoreLoop(ops).run(task(), AgentState(task_id="t-1"), "go")
    assert out.kind == "completed"
    result = out.state.history[2].item
    assert isinstance(result, ToolResultItem)
    assert result.result.is_error
    assert "no such participant" in (result.result.content[0].text or "")


async def test_spawn_subtask_waits_for_the_child_then_completes() -> None:
    ops, _ = await host(
        scripted("", tool_calls=[PLAN_CALL]),
        scripted(
            "",
            tool_calls=[
                ToolCall(
                    call_id="c2",
                    name="spawn_subtask",
                    arguments={"name": "Check", "goal": "Check the ledger", "step": "gather-facts"},
                )
            ],
        ),
        scripted("Waiting on the check."),
        scripted("Done."),
    )
    loop = CoreLoop(ops)
    first = await loop.run(task(), AgentState(task_id="t-1"), "go")
    assert first.kind == "waiting_for_children"
    assert first.task.state == TaskState.TASK_STATE_WORKING
    assert len(ops.spawned) == 1
    child, command = ops.spawned[0]
    assert command.kind == "spawn_subtask"
    assert first.task.ext.sub_tasks == (child,)
    plan = first.task.ext.plan
    assert plan is not None
    assert plan.step("gather-facts").linked_tasks == (child,)
    ops.resolved_children.add(child.task_id)
    second = await loop.run(first.task, first.state, None)
    assert second.kind == "completed"


async def test_an_executor_can_fail_the_task_at_the_completion_predicate() -> None:
    ops, _ = await host(scripted("done"))

    async def veto(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, TaskCompleteIn)
        return ctx.model_copy(update={"result": CompletionDecision.FAIL, "reason": "no evidence"})

    ops.hooks.register(FunctionExecutor("veto", veto, priority=10, points=[TASK_COMPLETE]))
    out = await CoreLoop(ops).run(task(), AgentState(task_id="t-1"), "go")
    assert out.kind == "failed"
    assert out.reason == "no evidence"
    assert out.task.state == TaskState.TASK_STATE_FAILED


async def test_unknown_tool_and_bad_arguments_become_error_results_and_the_loop_goes_on() -> None:
    ops, _ = await host(
        scripted(
            "",
            tool_calls=[
                ToolCall(call_id="c1", name="shell.exec", arguments={"cmd": "rm -rf /"}),
                ToolCall(call_id="c2", name="create_plan", arguments={"steps": []}),
            ],
        ),
        scripted("ok"),
    )
    out = await CoreLoop(ops).run(task(), AgentState(task_id="t-1"), "go")
    assert out.kind == "completed"
    results = [e.item for e in out.state.history if isinstance(e.item, ToolResultItem)]
    assert [r.result.is_error for r in results] == [True, True]
    assert out.task.ext.plan is None


async def test_turn_limit_fails_the_task() -> None:
    ops, _ = await host(*(scripted("", tool_calls=[PLAN_CALL]) for _ in range(3)))
    out = await CoreLoop(ops, max_turns=3).run(task(), AgentState(task_id="t-1"), "go")
    assert out.kind == "failed"
    assert out.task.state == TaskState.TASK_STATE_FAILED
