"""The ``help.decided.in`` default body (R12.4): one decision, LLM-made, always validated.

Given a ``HelpNeed`` and the task, the body asks the LLM for a ``HelpDecision`` as
structured output, runs ``validate_decision``, and on an objection re-runs the body once
with the objection in context. An executor replaces the body by setting ``result``; the
validator runs regardless.
"""

from __future__ import annotations

import json
from typing import cast

from tiny_harness.harness.channels.models import (
    HelpDecision,
    HelpNeed,
    HelpRoute,
    validate_decision,
)
from tiny_harness.harness.core import HarnessTask, render_participants, render_task
from tiny_harness.harness.hooks import (
    DEFAULT_BODY_PRIORITY,
    FunctionExecutor,
    HookContext,
    HookManager,
    HookPoint,
    Operation,
    Phase,
)
from tiny_harness.harness.models import LLM, LLMRequest, MessageItem, Role
from tiny_harness.jsontypes import JsonObject, JsonSchema

HELP_DECIDED = HookPoint(operation=Operation.HELP_DECIDED, phase=Phase.IN)

DECISION_INSTRUCTIONS = (
    "You route a request for help on a task. Decide whether the need is a small input, "
    "opinion or judgement call one message can answer (route 'ask') or work that another "
    "participant must finish before the task can complete (route 'create_task'). Answer "
    "with JSON matching the schema."
)


class HelpDecidedIn(HookContext):
    need: HelpNeed
    task_text: str
    participants_text: str
    objection: str | None = None
    result: HelpDecision | None = None


def decision_schema() -> JsonSchema:
    schema = cast(JsonSchema, HelpDecision.model_json_schema())
    return schema


def register_default(hooks: HookManager, llm: LLM) -> None:
    async def body(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, HelpDecidedIn)
        if ctx.result is not None:
            return None
        prompt = (
            f"Task:\n{ctx.task_text}\n\nParticipants:\n{ctx.participants_text}\n\n"
            f"Need: {ctx.need.model_dump_json()}"
        )
        if ctx.objection:
            prompt += f"\n\nYour previous decision was rejected: {ctx.objection}"
        response = await llm.invoke(
            LLMRequest(
                instructions=DECISION_INSTRUCTIONS,
                input=(MessageItem(role=Role.USER, text=prompt),),
                response_format=decision_schema(),
            )
        )
        raw = cast(object, json.loads(response.output_text or "{}"))
        decision = HelpDecision.model_validate(
            cast(JsonObject, raw) if isinstance(raw, dict) else {}
        )
        return ctx.model_copy(update={"result": decision})

    hooks.register(
        FunctionExecutor(
            "help.decided", body, priority=DEFAULT_BODY_PRIORITY, points=[HELP_DECIDED]
        )
    )


async def decide(
    hooks: HookManager, *, need: HelpNeed, task: HarnessTask, correlation_id: str
) -> HelpDecision:
    """Run the body, validate, re-run once on an objection; the second objection raises."""
    ctx = HelpDecidedIn(
        task_id=task.id,
        correlation_id=correlation_id,
        need=need,
        task_text=render_task(task),
        participants_text=render_participants(task),
    )
    out = await hooks.run(HELP_DECIDED, ctx)
    decision = out.result or HelpDecision(
        route=HelpRoute.CREATE_TASK if need.blocking_work else HelpRoute.ASK,
        participant_id=need.participant_id or "",
        question=need.question,
        options=need.options,
        goal=need.question,
    )
    objection = validate_decision(need, decision)
    if objection is None:
        return decision
    retry = await hooks.run(
        HELP_DECIDED, ctx.model_copy(update={"objection": objection, "result": None})
    )
    decision = retry.result or decision
    objection = validate_decision(need, decision)
    if objection is not None:
        raise ValueError(f"help decision rejected twice: {objection}")
    return decision


__all__ = [
    "DECISION_INSTRUCTIONS",
    "HELP_DECIDED",
    "HelpDecidedIn",
    "decide",
    "decision_schema",
    "register_default",
]
