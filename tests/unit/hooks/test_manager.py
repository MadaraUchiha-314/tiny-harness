"""The hook executor chain (R2.1-R2.5): order, replacement, pass-through, abort, bodies."""

from __future__ import annotations

import pytest

from tiny_harness.errors import AbortReason, HookAbort
from tiny_harness.harness.hooks import (
    DEFAULT_BODY_PRIORITY,
    FunctionExecutor,
    HookContext,
    HookExecutor,
    HookManager,
    HookPoint,
    Operation,
    Phase,
    all_hook_points,
)


class Greeting(HookContext):
    text: str
    result: str | None = None


LLM_PRE = HookPoint(operation=Operation.LLM_INVOKED, phase=Phase.PRE)
PLAN_IN = HookPoint(operation=Operation.PLAN_CREATED, phase=Phase.IN)


def ctx(text: str = "hello") -> Greeting:
    return Greeting(task_id="t1", correlation_id="c1", text=text)


def appender(
    name: str, *, priority: int = 500, points: list[HookPoint] | None = None
) -> FunctionExecutor:
    async def handle(point: HookPoint, c: HookContext) -> HookContext | None:
        assert isinstance(c, Greeting)
        return c.model_copy(update={"text": f"{c.text}>{name}"})

    return FunctionExecutor(name, handle, priority=priority, points=points)


def test_catalogue_has_every_operation_in_three_phases() -> None:
    points = all_hook_points()
    assert len(points) == len(Operation) * 3
    assert str(LLM_PRE) == "llm.invoked.pre"
    assert {op.value for op in Operation} >= {
        "request.received",
        "task.created",
        "task.state_changed",
        "context.created",
        "llm.invoked",
        "tool_calls.extracted",
        "tool.invoked",
        "system_one.invoked",
        "plan.created",
        "step.started",
        "step.finished",
        "subtask.spawned",
        "help.requested",
        "channel.sent",
        "channel.received",
        "compaction.trigger",
        "persistence.read",
        "persistence.write",
        "activity.failed",
        "activity.retried",
        "heartbeat.tick",
        "shutdown",
    }


async def test_executors_run_by_priority_then_registration_order() -> None:
    manager = HookManager()
    manager.register(appender("b", priority=500))
    manager.register(appender("c", priority=500))
    manager.register(appender("a", priority=100))
    out = await manager.run(LLM_PRE, ctx())
    assert out.text == "hello>a>b>c"


async def test_none_passes_the_context_through_unchanged() -> None:
    seen: list[str] = []

    async def observe(point: HookPoint, c: HookContext) -> HookContext | None:
        assert isinstance(c, Greeting)
        seen.append(c.text)
        return None

    manager = HookManager()
    manager.register(FunctionExecutor("observer", observe))
    manager.register(appender("x"))
    out = await manager.run(LLM_PRE, ctx())
    assert seen == ["hello"] and out.text == "hello>x"


async def test_points_filter_which_executors_run() -> None:
    manager = HookManager()
    manager.register(appender("only-plan", points=[PLAN_IN]))
    manager.register(appender("all"))
    assert (await manager.run(LLM_PRE, ctx())).text == "hello>all"
    assert (await manager.run(PLAN_IN, ctx())).text == "hello>only-plan>all"


async def test_abort_propagates_and_stops_the_chain() -> None:
    async def refuse(point: HookPoint, c: HookContext) -> HookContext | None:
        raise HookAbort("not allowed", reason=AbortReason.POLICY)

    manager = HookManager()
    manager.register(FunctionExecutor("policy", refuse, priority=1))
    manager.register(appender("never"))
    with pytest.raises(HookAbort) as info:
        await manager.run(LLM_PRE, ctx())
    assert info.value.reason is AbortReason.POLICY


async def test_a_context_of_another_type_is_a_programming_error() -> None:
    class Other(HookContext):
        pass

    async def swap(point: HookPoint, c: HookContext) -> HookContext | None:
        return Other(task_id="t1", correlation_id="c1")

    manager = HookManager()
    manager.register(FunctionExecutor("swap", swap))
    with pytest.raises(TypeError, match="swap"):
        await manager.run(LLM_PRE, ctx())


async def test_a_lower_priority_executor_overrides_the_default_body() -> None:
    async def default_body(point: HookPoint, c: HookContext) -> HookContext | None:
        assert isinstance(c, Greeting)
        if c.result is None:
            return c.model_copy(update={"result": "default"})
        return None

    async def plugin_body(point: HookPoint, c: HookContext) -> HookContext | None:
        assert isinstance(c, Greeting)
        return c.model_copy(update={"result": "plugin"})

    manager = HookManager()
    manager.register(FunctionExecutor("default", default_body, priority=DEFAULT_BODY_PRIORITY))
    assert (await manager.run(PLAN_IN, ctx())).result == "default"
    manager.register(FunctionExecutor("plugin", plugin_body, priority=200))
    assert (await manager.run(PLAN_IN, ctx())).result == "plugin"


def test_function_executor_satisfies_the_protocol() -> None:
    assert isinstance(appender("x"), HookExecutor)
