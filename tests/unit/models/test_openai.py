"""The OpenAI adapter (R18.1, R18.3, R18.5, R10.3) against recorded Responses API bodies."""

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
from tiny_harness.harness.models.openai_adapter import build_params
from tiny_harness.harness.tools import ToolCall, ToolDefinition, ToolResult

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openai"
JsonObject = dict[str, object]
Handler = Callable[[httpx2.Request], httpx2.Response]


def client_for(handler: Handler) -> AsyncOpenAI:
    transport = httpx2.MockTransport(handler)
    return AsyncOpenAI(
        api_key="sk-test", max_retries=0, http_client=httpx2.AsyncClient(transport=transport)
    )


def llm(handler: Handler) -> OpenAILLM:
    return OpenAILLM(SecretStr("sk-test"), client=client_for(handler))


def fixture(name: str) -> JsonObject:
    return cast(JsonObject, json.loads((FIXTURES / name).read_text()))


def request() -> LLMRequest:
    return LLMRequest(
        instructions="be brief",
        input=(
            MessageItem(role=Role.USER, text="Refund order #48213"),
            ToolCallItem(
                call=ToolCall(call_id="call_0", name="policy.lookup", arguments={"topic": "damage"})
            ),
            ToolResultItem(result=ToolResult.text("call_0", "refund within 14 days")),
        ),
        tools=(
            ToolDefinition(
                name="orders.get_order",
                description="Fetch an order",
                input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}},
            ),
        ),
        cache_key="task-7f3a",
    )


def test_request_mapping_keeps_the_prefix_static_and_caching_on() -> None:
    params = cast(JsonObject, build_params(request(), model="gpt-6.1-sol", max_output_tokens=2_000))
    assert params["model"] == "gpt-6.1-sol" and params["instructions"] == "be brief"
    assert params["store"] is False and params["prompt_cache_key"] == "task-7f3a"
    assert params["max_output_tokens"] == 2_000
    items = cast(list[JsonObject], params["input"])
    assert items[0] == {"role": "user", "content": "Refund order #48213"}
    assert items[1]["type"] == "function_call" and items[1]["arguments"] == '{"topic": "damage"}'
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "call_0",
        "output": "refund within 14 days",
    }
    tools = cast(list[JsonObject], params["tools"])
    assert tools[0]["type"] == "function" and tools[0]["name"] == "orders.get_order"
    assert "text" not in params


async def test_tool_calls_and_cached_tokens_are_parsed() -> None:
    seen: list[JsonObject] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(cast(JsonObject, json.loads(req.content)))
        return httpx2.Response(200, json=fixture("response_tool_call.json"))

    response = await llm(handler).invoke(request())
    assert response.output_text == "Checking the order."
    assert [c.name for c in response.tool_calls] == ["orders.get_order"]
    assert response.tool_calls[0].arguments == {"order_id": "48213"}
    assert response.usage.input_tokens == 6812 and response.usage.cached_tokens == 5120
    assert response.usage.output_tokens == 341 and response.finish is FinishReason.TOOL_CALLS
    assert seen[0]["prompt_cache_key"] == "task-7f3a" and seen[0]["store"] is False


async def test_incomplete_output_is_a_length_finish() -> None:
    response = await llm(lambda r: httpx2.Response(200, json=fixture("response_text.json"))).invoke(
        request()
    )
    assert response.finish is FinishReason.LENGTH and response.output_text == "The order qualifies"


async def test_provider_retries_disabled_and_failures_translated() -> None:
    attempts = 0

    def rate_limited(req: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(429, json={"error": {"message": "slow down"}})

    with pytest.raises(RetryableProviderError) as info:
        await llm(rate_limited).invoke(request())
    assert info.value.status == 429 and info.value.provider == "openai" and attempts == 1
    with pytest.raises(RetryableProviderError):
        await llm(lambda r: httpx2.Response(503, json={"error": {"message": "down"}})).invoke(
            request()
        )
    with pytest.raises(ProviderError) as bad:
        await llm(lambda r: httpx2.Response(400, json={"error": {"message": "bad"}})).invoke(
            request()
        )
    assert bad.value.status == 400


async def test_stream_yields_deltas_calls_and_the_final_response() -> None:
    body = (FIXTURES / "stream.sse").read_text()

    def handler(r: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})

    events = [e async for e in llm(handler).stream(request())]
    kinds = [e.kind for e in events]
    assert kinds == ["text_delta", "text_delta", "tool_call", "done"]
    assert "".join(e.text or "" for e in events if e.kind == "text_delta") == "Checking the order."
    assert events[2].call is not None and events[2].call.name == "orders.get_order"
    assert events[3].response is not None and events[3].response.usage.cached_tokens == 5120
