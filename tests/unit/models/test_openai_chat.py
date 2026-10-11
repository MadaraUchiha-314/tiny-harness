"""The OpenAI adapter over Chat Completions (issue-19 R3, R5) against recorded bodies:
request mapping, parsing, the finish rule, streaming assembly and error translation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from tiny_harness.errors import ProviderError, RetryableProviderError
from tiny_harness.harness.models import (
    FinishReason,
    LLMRequest,
    MessageItem,
    OpenAILLM,
    Role,
    ToolCallItem,
    ToolResultItem,
)
from tiny_harness.harness.models.openai_chat import build_chat_params
from tiny_harness.harness.tools import ToolCall, ToolDefinition, ToolResult

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openai" / "chat"
JsonObject = dict[str, object]
Handler = Callable[[httpx2.Request], httpx2.Response]


def llm(handler: Handler, *, api_key: str | None = "sk-test") -> OpenAILLM:
    client = AsyncOpenAI(
        api_key="sk-test",
        base_url="http://127.0.0.1:11434/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    key = SecretStr(api_key) if api_key is not None else None
    return OpenAILLM(
        key,
        model="qwen3:8b",
        base_url="http://127.0.0.1:11434/v1",
        api="chat_completions",
        client=client,
    )


def fixture(name: str) -> JsonObject:
    return cast(JsonObject, json.loads((FIXTURES / name).read_text()))


def answering(name: str, seen: list[httpx2.Request] | None = None) -> Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if seen is not None:
            seen.append(request)
        return httpx2.Response(200, json=fixture(name))

    return handler


def tools() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            name="orders.get_order",
            description="Fetch an order",
            input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}},
        ),
        ToolDefinition(
            name="policy.lookup",
            description="Look up a policy",
            input_schema={"type": "object", "properties": {"topic": {"type": "string"}}},
        ),
    )


def request(**overrides: object) -> LLMRequest:
    values: dict[str, object] = {
        "instructions": "be brief",
        "input": (
            MessageItem(role=Role.USER, text="Refund order #48213"),
            MessageItem(role=Role.ASSISTANT, text="Let me look."),
            ToolCallItem(
                call=ToolCall(call_id="call_0", name="policy.lookup", arguments={"topic": "damage"})
            ),
            ToolCallItem(
                call=ToolCall(
                    call_id="call_1", name="orders.get_order", arguments={"order_id": "48213"}
                )
            ),
            ToolResultItem(result=ToolResult.text("call_0", "refund within 14 days")),
            ToolResultItem(result=ToolResult.text("call_1", "delivered damaged")),
        ),
        "tools": tools(),
        "cache_key": "task-7f3a",
    }
    values.update(overrides)
    return LLMRequest.model_validate(values)


# R3.3 — the request.


def test_request_mapping() -> None:
    params = cast(JsonObject, build_chat_params(request(), model="qwen3:8b", max_output_tokens=900))
    assert params["model"] == "qwen3:8b" and params["max_tokens"] == 900
    assert "store" not in params and "prompt_cache_key" not in params
    assert "response_format" not in params
    messages = cast(list[JsonObject], params["messages"])
    assert messages[0] == {"role": "system", "content": "be brief"}
    assert messages[1] == {"role": "user", "content": "Refund order #48213"}
    assert messages[2] == {"role": "assistant", "content": "Let me look."}
    grouped = messages[3]
    assert grouped["role"] == "assistant" and grouped["content"] is None
    calls = cast(list[JsonObject], grouped["tool_calls"])
    assert [c["id"] for c in calls] == ["call_0", "call_1"]
    assert calls[0] == {
        "id": "call_0",
        "type": "function",
        "function": {"name": "policy_lookup", "arguments": '{"topic": "damage"}'},
    }
    assert messages[4] == {
        "role": "tool",
        "tool_call_id": "call_0",
        "content": "refund within 14 days",
    }
    assert messages[5]["tool_call_id"] == "call_1" and len(messages) == 6
    wire_tools = cast(list[JsonObject], params["tools"])
    function = cast(JsonObject, wire_tools[0]["function"])
    assert wire_tools[0]["type"] == "function" and function["name"] == "orders_get_order"
    assert function["parameters"] == tools()[0].input_schema and function["strict"] is False


def test_request_mapping_with_structured_output_and_a_request_budget() -> None:
    schema: JsonObject = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    params = cast(
        JsonObject,
        build_chat_params(
            request(tools=(), response_format=schema, max_output_tokens=50),
            model="qwen3:8b",
            max_output_tokens=900,
        ),
    )
    assert params["max_tokens"] == 50 and "tools" not in params
    assert params["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "response", "schema": schema, "strict": True},
    }


async def test_the_request_reaches_chat_completions() -> None:
    seen: list[httpx2.Request] = []
    await llm(answering("text.json", seen)).invoke(request())
    assert str(seen[0].url) == "http://127.0.0.1:11434/v1/chat/completions"


async def test_a_keyless_call_has_no_authorization_header() -> None:
    seen: list[httpx2.Request] = []
    await llm(answering("text.json", seen), api_key=None).invoke(request())
    assert "authorization" not in seen[0].headers


# R3.3 — parsing and the finish rule.


async def test_text_and_usage_are_parsed() -> None:
    response = await llm(answering("text.json")).invoke(request())
    assert response.output_text == "The order qualifies for a refund."
    assert response.tool_calls == () and response.finish is FinishReason.STOP
    assert response.usage.input_tokens == 812 and response.usage.output_tokens == 21
    assert response.usage.cached_tokens == 512 and response.model == "qwen3:8b"


async def test_tool_calls_are_decoded_through_the_wire_names() -> None:
    response = await llm(answering("tool_calls.json")).invoke(request())
    assert response.output_text == "Checking the order."
    assert [(c.call_id, c.name) for c in response.tool_calls] == [
        ("call_a", "orders.get_order"),
        ("call_b", "policy.lookup"),
    ]
    assert response.tool_calls[0].arguments == {"order_id": "48213"}
    assert response.finish is FinishReason.TOOL_CALLS


@pytest.mark.parametrize(
    ("name", "finish", "text"),
    [
        ("tool_calls_stop.json", FinishReason.TOOL_CALLS, ""),
        ("refusal.json", FinishReason.REFUSAL, "I can't help with that."),
        ("content_filter.json", FinishReason.REFUSAL, ""),
        ("length.json", FinishReason.LENGTH, "The order qual"),
    ],
)
async def test_the_finish_rule(name: str, finish: FinishReason, text: str) -> None:
    response = await llm(answering(name)).invoke(request())
    assert response.finish is finish and response.output_text == text


# R3.4 — absent fields are absent, not failures.


async def test_missing_usage_and_call_ids_are_tolerated() -> None:
    response = await llm(answering("minimal.json")).invoke(request())
    assert response.usage.input_tokens == 0 and response.usage.output_tokens == 0
    assert response.usage.cached_tokens == 0
    assert [c.call_id for c in response.tool_calls] == ["call_0"]


# R3.3 — streaming.


def streaming(body: str) -> Handler:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})

    return handler


async def test_stream_assembles_deltas_fragmented_calls_and_usage() -> None:
    seen: list[httpx2.Request] = []
    body = (FIXTURES / "stream.sse").read_text()

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return streaming(body)(request)

    events = [e async for e in llm(handler).stream(request())]
    assert [e.kind for e in events] == [
        "text_delta",
        "text_delta",
        "tool_call",
        "tool_call",
        "done",
    ]
    assert "".join(e.text or "" for e in events if e.kind == "text_delta") == "Checking the order."
    calls = [e.call for e in events if e.call is not None]
    assert [(c.call_id, c.name, c.arguments) for c in calls] == [
        ("call_a", "orders.get_order", {"order_id": "48213"}),
        ("call_b", "policy.lookup", {"topic": "damage"}),
    ]
    done = events[-1].response
    assert done is not None and done.finish is FinishReason.TOOL_CALLS
    assert done.output_text == "Checking the order." and done.tool_calls == tuple(calls)
    assert done.usage.input_tokens == 812 and done.usage.cached_tokens == 512
    sent = cast(JsonObject, json.loads(seen[0].content))
    assert sent["stream"] is True and sent["stream_options"] == {"include_usage": True}


async def test_a_stream_without_usage_still_completes() -> None:
    lines = (FIXTURES / "stream.sse").read_text().split("\n\n")
    body = "\n\n".join(line for line in lines if '"usage"' not in line)
    events = [e async for e in llm(streaming(body)).stream(request())]
    done = events[-1].response
    assert done is not None and done.usage.input_tokens == 0


# R5 — errors.


@pytest.mark.parametrize(("status", "retryable"), [(429, True), (503, True), (400, False)])
async def test_status_errors_are_translated(status: int, retryable: bool) -> None:
    expected = RetryableProviderError if retryable else ProviderError
    with pytest.raises(expected) as caught:
        await llm(lambda _: httpx2.Response(status, json={"error": {"message": "x"}})).invoke(
            request()
        )
    assert caught.value.status == status


async def test_a_refused_connection_is_retryable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(RetryableProviderError):
        await llm(refuse).invoke(request())


@pytest.mark.parametrize("name", ["no_choices.json", "bad_arguments.json"])
async def test_abuse_an_unparseable_body_is_a_provider_error(name: str) -> None:
    with pytest.raises(ProviderError) as caught:
        await llm(answering(name)).invoke(request())
    assert caught.value.status == 200 and "chat_completions" in str(caught.value)


async def test_abuse_unparseable_streamed_arguments_are_a_provider_error() -> None:
    body = (FIXTURES / "stream.sse").read_text().replace('\\"48213\\"}', "oops")
    with pytest.raises(ProviderError):
        async for _ in llm(streaming(body)).stream(request()):
            pass


async def test_abuse_deeply_nested_arguments_are_a_provider_error() -> None:
    body = fixture("tool_calls.json")
    choices = cast(list[JsonObject], body["choices"])
    message = cast(JsonObject, choices[0]["message"])
    calls = cast(list[JsonObject], message["tool_calls"])
    cast(JsonObject, calls[0]["function"])["arguments"] = "[" * 100_000 + "]" * 100_000
    with pytest.raises(ProviderError):
        await llm(lambda _: httpx2.Response(200, json=body)).invoke(request())


async def test_abuse_an_empty_stream_is_a_provider_error() -> None:
    with pytest.raises(ProviderError):
        async for _ in llm(streaming("data: [DONE]\n\n")).stream(request()):
            pass


async def test_abuse_a_truncated_stream_emits_no_call_and_is_a_provider_error() -> None:
    lines = (FIXTURES / "stream.sse").read_text().split("\n\n")
    cut = "\n\n".join(lines[:5]) + "\n\ndata: [DONE]\n\n"  # ends mid tool call
    seen: list[str] = []
    with pytest.raises(ProviderError):
        async for event in llm(streaming(cut)).stream(request()):
            seen.append(event.kind)
    assert "tool_call" not in seen and "done" not in seen
