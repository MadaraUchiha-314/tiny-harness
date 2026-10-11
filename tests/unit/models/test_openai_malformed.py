"""A 2xx body the Responses API mapping cannot parse is a ``ProviderError``, never an
unhandled exception (issue-19 R5.3, abuse case 4) — on invoke and on stream."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr

from tiny_harness.errors import ProviderError
from tiny_harness.harness.models import LLMRequest, MessageItem, OpenAILLM, Role

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openai"
JsonObject = dict[str, object]


def llm(handler: Callable[[httpx2.Request], httpx2.Response]) -> OpenAILLM:
    client = AsyncOpenAI(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return OpenAILLM(SecretStr("sk-test"), client=client)


def request() -> LLMRequest:
    return LLMRequest(instructions="be brief", input=(MessageItem(role=Role.USER, text="hi"),))


def tool_call_body() -> JsonObject:
    return cast(JsonObject, json.loads((FIXTURES / "response_tool_call.json").read_text()))


def bad_arguments() -> JsonObject:
    body = tool_call_body()
    output = cast(list[JsonObject], body["output"])
    output[1]["arguments"] = "{not json"
    return body


def bad_usage() -> JsonObject:
    body = tool_call_body()
    body["usage"] = {"input_tokens": "many", "output_tokens": None}
    return body


@pytest.mark.parametrize("body", [bad_arguments(), bad_usage()], ids=["arguments", "usage"])
async def test_abuse_an_unparseable_body_is_a_provider_error(body: JsonObject) -> None:
    with pytest.raises(ProviderError) as caught:
        await llm(lambda _: httpx2.Response(200, json=body)).invoke(request())
    assert caught.value.status == 200


async def test_abuse_a_body_that_is_not_json_is_a_provider_error() -> None:
    with pytest.raises(ProviderError):
        await llm(
            lambda _: httpx2.Response(
                200, content=b"<html>proxy</html>", headers={"content-type": "application/json"}
            )
        ).invoke(request())


async def test_abuse_unparseable_streamed_tool_arguments_are_a_provider_error() -> None:
    sse = (
        (FIXTURES / "stream.sse")
        .read_text()
        .replace('"arguments": "{\\"order_id\\": \\"48213\\"}"', '"arguments": "{not json"')
    )
    assert "{not json" in sse
    events = llm(
        lambda _: httpx2.Response(
            200, content=sse.encode(), headers={"content-type": "text/event-stream"}
        )
    ).stream(request())
    with pytest.raises(ProviderError) as caught:
        async for _ in events:
            pass
    assert caught.value.status == 200


DEEP = "[" * 100_000 + "]" * 100_000  # json.loads raises RecursionError, not ValueError


async def test_abuse_deeply_nested_arguments_are_a_provider_error() -> None:
    body = tool_call_body()
    cast(list[JsonObject], body["output"])[1]["arguments"] = DEEP
    with pytest.raises(ProviderError):
        await llm(lambda _: httpx2.Response(200, json=body)).invoke(request())
