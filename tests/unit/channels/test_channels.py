"""Channels and help routing (R12.1, R12.4, R13.1-R13.3)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tiny_harness.errors import ChannelMembershipError
from tiny_harness.harness.channels import (
    A2AChannel,
    ChannelMessage,
    HelpDecision,
    HelpNeed,
    HelpRoute,
    decide,
    register_default,
    validate_decision,
)
from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookManager, HookPoint
from tiny_harness.harness.models import FakeLLM, scripted
from tiny_harness.harness.persistence import ChannelMessageRecord, Filter, SqliteStore
from tiny_harness.harness.tools import ContentPart

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def message(sender: str, text: str, kind: str = "message") -> ChannelMessage:
    return ChannelMessage(
        id=f"m-{sender}-{text[:4]}",
        channel_id="task-7f3a",
        sender=sender,
        parts=(ContentPart(kind="text", text=text),),
        at=NOW,
        kind=kind,  # type: ignore[arg-type]
    )


def task() -> HarnessTask:
    return HarnessTask.new(
        "t-1",
        "ctx-1",
        TaskExtensionData(
            name="Refund",
            goal="Resolve",
            participants=(
                Participant(id="support-agent", kind="agent", role=Role.ASSIGNEE),
                Participant(id="u-1", kind="human", role=Role.REPORTER),
            ),
        ),
    )


async def test_send_persists_before_emitting_and_checks_membership() -> None:
    store = SqliteStore(":memory:")
    emitted: list[ChannelMessage] = []

    async def emit(m: ChannelMessage) -> None:
        persisted = await store.query(ChannelMessageRecord, Filter(task_id="t-1"))
        assert [r.id for r in persisted] == [m.id], "persisted before delivery"
        emitted.append(m)

    channel = A2AChannel(
        EntityRef(kind=EntityKind.CHANNEL, id="task-7f3a"),
        task_id="t-1",
        context_id="ctx-1",
        members=["support-agent", "u-1"],
        store=store,
        emitter=emit,
    )
    await channel.send(message("support-agent", "Which address?", "help_request"))
    assert [m.kind for m in emitted] == ["help_request"]
    await channel.accept(message("u-1", "Use #48213."))
    received = [m async for m in channel.receive()]
    assert [m.text for m in received] == ["Use #48213."]
    with pytest.raises(ChannelMembershipError):
        await channel.accept(message("stranger", "hi"))
    with pytest.raises(ChannelMembershipError):
        await channel.send(message("stranger", "hi"))
    assert len(await store.query(ChannelMessageRecord, Filter(task_id="t-1"))) == 2


def test_validator_rejects_an_ask_for_blocking_work() -> None:
    need = HelpNeed(question="Ship the replacement", blocking_work=True, participant_id="u-1")
    ask = HelpDecision(route=HelpRoute.ASK, participant_id="u-1", question="Ship it?")
    assert validate_decision(need, ask) is not None
    task_route = HelpDecision(
        route=HelpRoute.CREATE_TASK, participant_id="u-1", goal="Ship the replacement"
    )
    assert validate_decision(need, task_route) is None


async def test_default_body_uses_structured_output_and_retries_once_on_objection() -> None:
    hooks = HookManager()
    llm = FakeLLM(
        [
            scripted('{"route": "ask", "participant_id": "u-1", "question": "Ship it?"}'),
            scripted(
                '{"route": "create_task", "participant_id": "u-1", "goal": "Ship the replacement"}'
            ),
        ]
    )
    register_default(hooks, llm)
    need = HelpNeed(question="Ship the replacement", blocking_work=True, participant_id="u-1")
    decision = await decide(hooks, need=need, task=task(), correlation_id="c")
    assert decision.route is HelpRoute.CREATE_TASK and decision.goal == "Ship the replacement"
    assert len(llm.requests) == 2 and llm.requests[0].response_format is not None
    second = llm.requests[1].input[0]
    assert "rejected" in getattr(second, "text", "")


async def test_a_plugin_body_replaces_the_default_but_is_still_validated() -> None:
    from tiny_harness.harness.channels.help import HELP_DECIDED, HelpDecidedIn

    hooks = HookManager()
    register_default(hooks, FakeLLM([]))

    async def always_ask(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, HelpDecidedIn)
        return ctx.model_copy(
            update={"result": HelpDecision(route=HelpRoute.ASK, participant_id="u-1", question="?")}
        )

    hooks.register(FunctionExecutor("plugin", always_ask, priority=10, points=[HELP_DECIDED]))
    small = HelpNeed(question="Which address?", participant_id="u-1")
    assert (await decide(hooks, need=small, task=task(), correlation_id="c")).route is HelpRoute.ASK
    blocking = HelpNeed(question="Ship it", blocking_work=True, participant_id="u-1")
    with pytest.raises(ValueError, match="rejected twice"):
        await decide(hooks, need=blocking, task=task(), correlation_id="c")
