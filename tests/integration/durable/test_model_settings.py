"""Feature: Per-task model and effort
Requirement: docs/specs/issue-25/requirements.md#R7

Every model call of a task uses the task's model and reasoning effort, else the
configured defaults: the turn, the compaction summary and the help decision.
"""

from __future__ import annotations

import uuid

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.integration.durable.conftest import (
    Harness,
    awaiting_next_message,
    close,
    message,
    send,
    start,
    task,
)
from tiny_harness.harness.channels import HelpDecision, HelpNeed, HelpRoute
from tiny_harness.harness.channels.help import decide, register_default
from tiny_harness.harness.core import HarnessTask
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.models import FakeLLM, ModelCatalog, scripted

pytestmark = pytest.mark.asyncio(loop_scope="module")


def ids() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return f"tq-{suffix}", f"t-{suffix}"


def choosing(task_id: str, model: str | None, effort: str | None) -> HarnessTask:
    """A task whose settings were chosen, as /model and /effort record them (R7.3, R8.3)."""
    base = task(task_id)
    return base.with_ext(base.ext.model_copy(update={"model": model, "reasoning_effort": effort}))


CATALOG = ModelCatalog(
    default="model-a",
    selectable=("model-a", "model-b", "model-small"),
    windows={"model-a": 128_000, "model-b": 128_000, "model-small": 400},
)


async def test_a_tasks_model_and_effort_reach_the_turn_and_the_compaction_summary(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Per-task model and effort
    Requirement: docs/specs/issue-25/requirements.md#R7

    Scenario: /model and /effort change the next model request, compaction and help included
        Given a task whose model is model-b and whose effort is high
        And a first message over the compaction budget
        When the task runs
        Then the compaction summary request carries model-b and high
        And the turn's request carries model-b and high
    """
    h = await Harness([scripted("summary"), scripted("Refunded.")], turn_budget_tokens=150).bind()
    h.engine.catalog = CATALOG
    tq, tid = ids()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(choosing(tid, "model-b", "high")),
            message("complaint " * 300, task_id=tid, message_id="m1"),
        )
        await awaiting_next_message(handle)
        await close(handle)
    summary, turn = h.llm.requests
    assert "Exchange:" in summary.input[0].text  # type: ignore[union-attr]
    assert (summary.model, summary.reasoning_effort) == ("model-b", "high")
    assert (turn.model, turn.reasoning_effort) == ("model-b", "high")


async def test_a_task_without_settings_uses_the_configured_defaults(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Per-task model and effort
    Requirement: docs/specs/issue-25/requirements.md#R7

    Scenario: A task without settings uses the configured defaults
        Given a catalog whose default is model-a and whose default effort is low
        When a task that chose nothing runs a turn
        Then the request carries model-a and low
    """
    h = await Harness([scripted("Hello.")]).bind()
    h.engine.catalog = CATALOG.model_copy(update={"default_effort": "low"})
    tq, tid = ids()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("hi", task_id=tid, message_id="m1")
        )
        await awaiting_next_message(handle)
        await close(handle)
    [turn] = h.llm.requests
    assert (turn.model, turn.reasoning_effort) == ("model-a", "low")


async def test_the_compaction_budget_follows_the_tasks_model(env: WorkflowEnvironment) -> None:
    """
    Feature: Per-task model and effort
    Requirement: docs/specs/issue-25/requirements.md#R7

    Scenario: The compaction budget follows the task's model
        Given model-small has a 400-token context window and model-a a large one
        When the same message reaches a task on each
        Then only the task on model-small compacts before its turn
    """
    h = await Harness([scripted("Fine."), scripted("summary"), scripted("Fine.")]).bind()
    h.engine.catalog = CATALOG
    tq, big, small = ids()[0], *(f"t-{uuid.uuid4().hex[:8]}" for _ in range(2))
    text = "complaint " * 200  # ~500 tokens: over 75 % of 400, well under 12 000
    async with h.worker(env.client, tq):
        for tid, model in ((big, "model-a"), (small, "model-small")):
            handle = await send(
                env.client,
                tq,
                start(choosing(tid, model, None)),
                message(text, task_id=tid, message_id=f"m-{tid}"),
            )
            await awaiting_next_message(handle)
            await close(handle)
    first, summary, second = h.llm.requests
    assert first.model == "model-a" and "Exchange:" not in str(first.input[0])
    assert summary.model == "model-small" and "Exchange:" in str(summary.input[0])
    assert second.model == "model-small"


async def test_the_help_decision_uses_the_tasks_model_and_effort() -> None:
    """The help-routing request (``help.decided.in``) uses ``settings_for`` too (R7.3)."""
    decision = HelpDecision(route=HelpRoute.ASK, participant_id="alice", question="Full?")
    llm = FakeLLM([scripted(decision.model_dump_json())])
    hooks = HookManager()
    register_default(hooks, llm, CATALOG.model_copy(update={"default_effort": "medium"}))
    need = HelpNeed(question="Full?", participant_id="alice")
    await decide(hooks, need=need, task=choosing("t-h", "model-b", None), correlation_id="c")
    [request] = llm.requests
    assert (request.model, request.reasoning_effort) == ("model-b", "medium")
