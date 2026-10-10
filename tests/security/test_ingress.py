"""Abuse case 6, wrapper variant: ingress is redacted before any hook or the history sees it."""

from __future__ import annotations

from tiny_harness.harness.core import AgentState, HarnessTask, TaskExtensionData
from tiny_harness.harness.core.inprocess import InProcessOperations
from tiny_harness.harness.entities import Registry
from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookManager, HookPoint
from tiny_harness.harness.models import FakeLLM, MessageItem
from tiny_harness.harness.persistence import SqliteStore
from tiny_harness.harness.security import MASK, Redactor

SECRET = "sk-abcdefghijklmnop0123"


async def test_ingress_redacted_before_history() -> None:
    hooks = HookManager()
    seen: list[str] = []

    async def observe(point: HookPoint, ctx: HookContext) -> HookContext | None:
        seen.append(ctx.model_dump_json())
        return None

    hooks.register(FunctionExecutor("observe", observe))
    ops = InProcessOperations(
        registry=Registry(),
        hooks=hooks,
        llm=FakeLLM([]),
        store=SqliteStore(":memory:"),
        system_prompt="",
        redactor=Redactor(secrets=["hunter2hunter2"]),
    )
    task = HarnessTask.new("t-1", "ctx-1", TaskExtensionData(name="n", goal="g"))
    state = await ops.ingest(
        task, AgentState(task_id="t-1"), f"my key {SECRET} and password hunter2hunter2"
    )
    item = state.history[0].item
    assert isinstance(item, MessageItem)
    assert SECRET not in item.text and "hunter2hunter2" not in item.text
    assert item.text == f"my key {MASK} and password {MASK}"
    assert seen and all(SECRET not in s and "hunter2hunter2" not in s for s in seen)
