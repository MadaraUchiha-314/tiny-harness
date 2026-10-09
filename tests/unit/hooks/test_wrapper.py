"""The hook-wrapped operation runner (R2.2-R2.4, abuse case 6)."""

from __future__ import annotations

import pytest

from tiny_harness.errors import AbortReason, HookAbort
from tiny_harness.harness.hooks import (
    FunctionExecutor,
    HookContext,
    HookManager,
    HookPoint,
    Operation,
    OperationRunner,
    Phase,
)
from tiny_harness.harness.security import MASK, Redactor


class Pre(HookContext):
    prompt: str


class Post(Pre):
    answer: str


PRE = HookPoint(operation=Operation.LLM_INVOKED, phase=Phase.PRE)
POST = HookPoint(operation=Operation.LLM_INVOKED, phase=Phase.POST)


async def body(ctx: Pre) -> str:
    return f"answer to [{ctx.prompt}]"


def post_of(pre: Pre, out: str) -> Post:
    return Post(
        task_id=pre.task_id, correlation_id=pre.correlation_id, prompt=pre.prompt, answer=out
    )


def pre(prompt: str) -> Pre:
    return Pre(task_id="t", correlation_id="c", prompt=prompt)


async def test_pre_replaces_the_input_and_post_replaces_the_output() -> None:
    hooks = HookManager()

    async def rewrite(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, Pre)
        return ctx.model_copy(update={"prompt": ctx.prompt.upper()})

    async def decorate(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, Post)
        return ctx.model_copy(update={"answer": ctx.answer + " (post)"})

    hooks.register(FunctionExecutor("rewrite", rewrite, points=[PRE]))
    hooks.register(FunctionExecutor("decorate", decorate, points=[POST]))
    out = await OperationRunner(hooks).run(
        Operation.LLM_INVOKED, pre("hi"), body, make_post=post_of, extract=lambda p: p.answer
    )
    assert out == "answer to [HI] (post)"


async def test_redaction_happens_before_hooks_see_the_context_and_on_the_output() -> None:
    hooks = HookManager()
    seen: list[str] = []

    async def observe(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, Pre)
        seen.append(ctx.prompt)
        return None

    hooks.register(FunctionExecutor("observe", observe, points=[PRE]))
    runner = OperationRunner(hooks, Redactor(secrets=["s3cr3t-value"]))
    out = await runner.run(
        Operation.LLM_INVOKED,
        pre("key is s3cr3t-value and Bearer abcdefghijklmnop"),
        body,
        make_post=post_of,
        extract=lambda p: p.answer,
    )
    assert seen == [f"key is {MASK} and {MASK}"]
    assert "s3cr3t-value" not in out and MASK in out


async def test_abort_propagates_and_skips_the_body() -> None:
    hooks = HookManager()
    ran = False

    async def refuse(point: HookPoint, ctx: HookContext) -> HookContext | None:
        raise HookAbort("policy", reason=AbortReason.POLICY)

    async def tracked(ctx: Pre) -> str:
        nonlocal ran
        ran = True
        return "x"

    hooks.register(FunctionExecutor("refuse", refuse, points=[PRE]))
    with pytest.raises(HookAbort):
        await OperationRunner(hooks).run(
            Operation.LLM_INVOKED, pre("hi"), tracked, make_post=post_of, extract=lambda p: p.answer
        )
    assert not ran


async def test_run_in_scrubs_and_runs_the_chain() -> None:
    class Body(HookContext):
        text: str
        result: str | None = None

    hooks = HookManager()

    async def default(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, Body)
        return ctx.model_copy(update={"result": ctx.text[::-1]})

    hooks.register(
        FunctionExecutor(
            "default",
            default,
            priority=1000,
            points=[HookPoint(operation=Operation.PLAN_CREATED, phase=Phase.IN)],
        )
    )
    runner = OperationRunner(hooks, Redactor(secrets=["topsecret"]))
    out = await runner.run_in(
        Operation.PLAN_CREATED, Body(task_id="t", correlation_id="c", text="topsecret-abc")
    )
    assert out.result == f"{MASK}-abc"[::-1]
