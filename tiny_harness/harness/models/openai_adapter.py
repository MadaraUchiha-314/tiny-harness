"""The OpenAI adapter over the Responses API (R18.1, R18.3, R18.5, R10.3).

The static prefix goes in ``instructions`` and the per-turn items in ``input``, so the
provider's prefix cache covers the prompt, the tool definitions and the participants on
every turn; ``prompt_cache_key`` is the task id and ``store=False`` keeps no server-side
state. The client runs with ``max_retries=0``: durable execution owns retrying, so a
429, 5xx, timeout or connection failure is raised as ``RetryableProviderError`` and any
other provider error as ``ProviderError``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from typing import cast

import openai
from openai import AsyncOpenAI
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseInputParam,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
)
from openai.types.responses.response_create_params import ResponseCreateParamsBase
from pydantic import SecretStr

from tiny_harness.errors import ProviderError, RetryableProviderError
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.models.llm import (
    LLM,
    FinishReason,
    LLMModelInfo,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    MessageItem,
    ToolCallItem,
    Usage,
)
from tiny_harness.harness.models.wire_names import WireNames
from tiny_harness.harness.tools import ContentPart, ToolCall, ToolDefinition
from tiny_harness.jsontypes import JsonObject, JsonValue

PROVIDER = "openai"
CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-6.1-sol": 1_050_000,
    "gpt-6-astra": 1_050_000,
    "gpt-6-luna": 400_000,
}
MIN_CACHEABLE_TOKENS = 1_024


def _result_text(parts: Sequence[ContentPart]) -> str:
    chunks: list[str] = []
    for part in parts:
        if part.kind == "text" and part.text is not None:
            chunks.append(part.text)
        elif part.data is not None:
            chunks.append(json.dumps(part.data, sort_keys=True))
    return "\n".join(chunks)


def build_input(request: LLMRequest, names: WireNames | None = None) -> ResponseInputParam:
    """The Responses API ``input`` list for the request's items."""
    names = names or WireNames(request.tools)
    items: list[JsonObject] = []
    for item in request.input:
        if isinstance(item, MessageItem):
            items.append({"role": item.role.value, "content": item.text})
        elif isinstance(item, ToolCallItem):
            items.append(
                {
                    "type": "function_call",
                    "call_id": item.call.call_id,
                    "name": names.encode(item.call.name),
                    "arguments": json.dumps(item.call.arguments),
                }
            )
        else:
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": item.result.call_id,
                    "output": _result_text(item.result.content),
                }
            )
    return cast(ResponseInputParam, items)


def build_tools(
    tools: Sequence[ToolDefinition], names: WireNames | None = None
) -> list[JsonObject]:
    names = names or WireNames(tools)
    return [
        {
            "type": "function",
            "name": names.encode(t.name),
            "description": t.description,
            "parameters": cast(JsonValue, t.input_schema),
            "strict": False,
        }
        for t in tools
    ]


def build_params(
    request: LLMRequest, *, model: str, max_output_tokens: int, names: WireNames | None = None
) -> ResponseCreateParamsBase:
    names = names or WireNames(request.tools)
    params: JsonObject = {
        "model": model,
        "instructions": request.instructions,
        "input": cast(JsonValue, build_input(request, names)),
        "store": False,
        "max_output_tokens": request.max_output_tokens or max_output_tokens,
    }
    if request.tools:
        params["tools"] = cast(JsonValue, build_tools(request.tools, names))
    if request.cache_key:
        params["prompt_cache_key"] = request.cache_key
    if request.response_format is not None:
        params["text"] = {
            "format": {
                "type": "json_schema",
                "name": "response",
                "schema": cast(JsonValue, request.response_format),
                "strict": True,
            }
        }
    return cast(ResponseCreateParamsBase, params)


def parse_response(response: Response, names: WireNames | None = None) -> LLMResponse:
    names = names or WireNames()
    texts: list[str] = []
    calls: list[ToolCall] = []
    refused = False
    for item in response.output:
        if isinstance(item, ResponseOutputMessage):
            for part in item.content:
                if isinstance(part, ResponseOutputText):
                    texts.append(part.text)
                else:
                    refused = True
                    texts.append(part.refusal)
        elif isinstance(item, ResponseFunctionToolCall):
            arguments = cast(object, json.loads(item.arguments or "{}"))
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}
            calls.append(
                ToolCall(
                    call_id=item.call_id,
                    name=names.decode(item.name),
                    arguments=cast(JsonObject, arguments),
                )
            )
    usage = response.usage
    cached = usage.input_tokens_details.cached_tokens if usage else 0
    if refused:
        finish = FinishReason.REFUSAL
    elif calls:
        finish = FinishReason.TOOL_CALLS
    elif response.incomplete_details and response.incomplete_details.reason == "max_output_tokens":
        finish = FinishReason.LENGTH
    else:
        finish = FinishReason.STOP
    return LLMResponse(
        output_text="".join(texts),
        tool_calls=tuple(calls),
        usage=Usage(
            input_tokens=usage.input_tokens if usage else 0,
            cached_tokens=cached,
            output_tokens=usage.output_tokens if usage else 0,
        ),
        model=response.model,
        finish=finish,
    )


def translate_error(exc: Exception) -> Exception:
    if isinstance(exc, openai.RateLimitError | openai.InternalServerError):
        return RetryableProviderError(str(exc), provider=PROVIDER, status=exc.status_code)
    if isinstance(exc, openai.APIConnectionError | openai.APITimeoutError):
        return RetryableProviderError(str(exc), provider=PROVIDER, status=0)
    if isinstance(exc, openai.APIStatusError):
        return ProviderError(str(exc), provider=PROVIDER, status=exc.status_code)
    return exc


class OpenAILLM(LLM):
    """``gpt-6.1-sol`` by default (the ticket's "GPT 6.1"); no SDK retries (R18.3)."""

    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str = "gpt-6.1-sol",
        timeout: timedelta = timedelta(seconds=60),
        max_output_tokens: int = 2_000,
        client: AsyncOpenAI | None = None,
    ) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.LLM, id=f"openai/{model}", version=None),
            LLMModelInfo(
                provider=PROVIDER,
                model=model,
                context_window_tokens=CONTEXT_WINDOWS.get(model, 400_000),
                min_cacheable_tokens=MIN_CACHEABLE_TOKENS,
            ),
        )
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._client = client or AsyncOpenAI(
            api_key=api_key.get_secret_value(), timeout=timeout.total_seconds(), max_retries=0
        )

    async def invoke(self, request: LLMRequest) -> LLMResponse:
        names = WireNames(request.tools)
        params = build_params(
            request, model=self._model, max_output_tokens=self._max_output_tokens, names=names
        )
        try:
            response = await self._client.responses.create(**params)
        except Exception as exc:
            raise translate_error(exc) from exc
        return parse_response(response, names)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        names = WireNames(request.tools)
        params = build_params(
            request, model=self._model, max_output_tokens=self._max_output_tokens, names=names
        )
        try:
            events = await self._client.responses.create(**params, stream=True)
            async for event in events:
                if isinstance(event, ResponseTextDeltaEvent):
                    yield LLMStreamEvent(kind="text_delta", text=event.delta)
                elif isinstance(event, ResponseOutputItemDoneEvent) and isinstance(
                    event.item, ResponseFunctionToolCall
                ):
                    arguments = cast(object, json.loads(event.item.arguments or "{}"))
                    if isinstance(arguments, dict):
                        yield LLMStreamEvent(
                            kind="tool_call",
                            call=ToolCall(
                                call_id=event.item.call_id,
                                name=names.decode(event.item.name),
                                arguments=cast(JsonObject, arguments),
                            ),
                        )
                elif isinstance(event, ResponseCompletedEvent):
                    yield LLMStreamEvent(
                        kind="done", response=parse_response(event.response, names)
                    )
        except Exception as exc:
            raise translate_error(exc) from exc


__all__ = [
    "CONTEXT_WINDOWS",
    "MIN_CACHEABLE_TOKENS",
    "OpenAILLM",
    "build_input",
    "build_params",
    "build_tools",
    "parse_response",
    "translate_error",
]
