"""The LLM and System One interfaces (R18.1, R18.2, R18.6) and their fakes."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tiny_harness.harness.models import (
    ChoiceAnswer,
    ChoiceQuestion,
    FakeLLM,
    FakeSystemOne,
    FinishReason,
    LLMRequest,
    MessageItem,
    NoulAnswer,
    NoulQuestion,
    Role,
    ScoreAnswer,
    ScoreQuestion,
    scripted,
)
from tiny_harness.harness.tools import ToolCall


def request(text: str = "hi") -> LLMRequest:
    return LLMRequest(instructions="be brief", input=(MessageItem(role=Role.USER, text=text),))


async def test_fake_llm_returns_scripted_responses_in_order_and_records_requests() -> None:
    llm = FakeLLM([scripted("one"), scripted("two", cached_tokens=50)])
    first = await llm.invoke(request("a"))
    second = await llm.invoke(request("b"))
    assert (first.output_text, second.output_text) == ("one", "two")
    assert second.usage.cached_tokens == 50 and second.finish is FinishReason.STOP
    assert [r.input[0].text for r in llm.requests if isinstance(r.input[0], MessageItem)] == [
        "a",
        "b",
    ]
    with pytest.raises(RuntimeError):
        await llm.invoke(request())


async def test_fake_llm_streams_text_then_calls_then_done() -> None:
    call = ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "1"})
    llm = FakeLLM([scripted("thinking", tool_calls=[call])])
    events = [e async for e in llm.stream(request())]
    assert [e.kind for e in events] == ["text_delta", "tool_call", "done"]
    assert events[2].response is not None and events[2].response.finish is FinishReason.TOOL_CALLS


async def test_fake_system_one_answers_every_question_within_the_shapes() -> None:
    model = FakeSystemOne()
    answers = await model.decide(
        "customer reports a cracked blender",
        {
            "refund": NoulQuestion(instructions="Is a refund warranted?"),
            "route": ChoiceQuestion(instructions="Pick", options={"ask": "ask", "task": "task"}),
            "severity": ScoreQuestion(instructions="Rate", levels=("low", "mid", "high")),
        },
        timeout=timedelta(milliseconds=200),
    )
    assert isinstance(answers["refund"], NoulAnswer) and answers["refund"].probability == 0.5
    route = answers["route"]
    assert isinstance(route, ChoiceAnswer) and route.choice == "ask"
    assert sum(route.probabilities.values()) == pytest.approx(1.0)
    severity = answers["severity"]
    assert isinstance(severity, ScoreAnswer) and severity.score == 1.0


async def test_fake_system_one_honours_scripted_answers() -> None:
    model = FakeSystemOne({"refund": NoulAnswer(probability=0.9)})
    answers = await model.decide(
        "s", {"refund": NoulQuestion(instructions="?")}, timeout=timedelta(seconds=1)
    )
    assert isinstance(answers["refund"], NoulAnswer) and answers["refund"].probability == 0.9
    assert model.calls[0][0] == "s"
