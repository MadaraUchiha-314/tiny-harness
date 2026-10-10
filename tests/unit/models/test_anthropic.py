"""The Anthropic adapter (R18.1, R21.4) against recorded Messages API bodies."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx2
import pytest
from anthropic import AsyncAnthropic
from pydantic import SecretStr

from tiny_harness.errors import ProviderError, RetryableProviderError
from tiny_harness.harness.models import (
    AnthropicLLM,
    FinishReason,
    LLMRequest,
    MessageItem,
    Role,
    ToolCallItem,
    ToolResultItem,
)
from tiny_harness.harness.models.anthropic_adapter import build_params
from tiny_harness.harness.tools import ToolCall, ToolDefinition, ToolResult

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "anthropic"
JsonObject = dict[str, object]
Handler = Callable[[httpx2.Request], httpx2.Response]


def llm(handler: Handler) -> AnthropicLLM:
    transport = httpx2.MockTransport(handler)
    client = AsyncAnthropic(
        api_key="ant-test", max_retries=0, http_client=httpx2.AsyncClient(transport=transport)
    )
    return AnthropicLLM(SecretStr("ant-test"), client=client)


def fixture(name: str) -> JsonObject:
    return cast(JsonObject, json.loads((FIXTURES / name).read_text()))


def request() -> LLMRequest:
    return LLMRequest(
        instructions="be brief",
        input=(
            MessageItem(role=Role.USER, text="Refund order #48213"),
            MessageItem(role=Role.USER, text="It arrived cracked."),
            ToolCallItem(
                call=ToolCall(
                    call_id="toolu_0", name="policy.lookup", arguments={"topic": "damage"}
                )
            ),
            ToolResultItem(result=ToolResult.text("toolu_0", "refund within 14 days")),
        ),
        tools=(
            ToolDefinition(
                name="orders.get_order", description="Fetch", input_schema={"type": "object"}
            ),
        ),
    )


def test_request_mapping_caches_the_system_prefix_and_merges_roles() -> None:
    params = build_params(request(), model="claude-opus-5-5", max_tokens=2_000)
    system = cast(list[JsonObject], params["system"])
    assert system[0]["cache_control"] == {"type": "ephemeral"} and system[0]["text"] == "be brief"
    messages = cast(list[JsonObject], params["messages"])
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    first = cast(list[JsonObject], messages[0]["content"])
    assert [b["type"] for b in first] == ["text", "text"]
    assert cast(list[JsonObject], messages[1]["content"])[0]["type"] == "tool_use"
    assert cast(list[JsonObject], messages[2]["content"])[0]["type"] == "tool_result"
    assert cast(list[JsonObject], params["tools"])[0]["name"] == "orders_get_order"


async def test_tool_use_and_cache_reads_are_parsed() -> None:
    response = await llm(
        lambda r: httpx2.Response(200, json=fixture("message_tool_use.json"))
    ).invoke(request())
    assert response.output_text == "Checking the order."
    assert (
        response.tool_calls[0].name == "orders.get_order"
        and response.tool_calls[0].call_id == "toolu_1"
    )
    assert response.usage.cached_tokens == 5120 and response.usage.input_tokens == 1692 + 5120
    assert response.finish is FinishReason.TOOL_CALLS


async def test_max_tokens_is_a_length_finish() -> None:
    response = await llm(lambda r: httpx2.Response(200, json=fixture("message_text.json"))).invoke(
        request()
    )
    assert response.finish is FinishReason.LENGTH


async def test_failures_are_translated_and_never_retried_by_the_sdk() -> None:
    attempts = 0

    def overloaded(req: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(
            529, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}}
        )

    with pytest.raises(RetryableProviderError) as info:
        await llm(overloaded).invoke(request())
    assert info.value.status == 529 and attempts == 1
    with pytest.raises(ProviderError):
        await llm(
            lambda r: httpx2.Response(
                401,
                json={"type": "error", "error": {"type": "authentication_error", "message": "x"}},
            )
        ).invoke(request())
