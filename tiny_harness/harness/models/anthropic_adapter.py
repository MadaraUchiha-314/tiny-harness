"""The Anthropic adapter over the Messages API (R18.1, R21.4): configurable, not exercised
end to end in this work item.

The static prefix is the ``system`` block with ``cache_control: ephemeral``, so the
provider caches it; tool calls and results map to ``tool_use`` and ``tool_result``
blocks; consecutive items of one role merge into one message, as the API requires. The
client runs with ``max_retries=0``; retryable failures become ``RetryableProviderError``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from typing import cast

import anthropic
from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam, TextBlock, ToolUseBlock
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
    Role,
    ToolCallItem,
    Usage,
)
from tiny_harness.harness.models.wire_names import WireNames
from tiny_harness.harness.tools import ContentPart, ToolCall, ToolDefinition
from tiny_harness.jsontypes import JsonObject, JsonValue

PROVIDER = "anthropic"
CONTEXT_WINDOWS: dict[str, int] = {"claude-opus-5-5": 1_000_000, "claude-fable-5-1": 1_000_000}


def _result_text(parts: Sequence[ContentPart]) -> str:
    chunks: list[str] = []
    for part in parts:
        if part.kind == "text" and part.text is not None:
            chunks.append(part.text)
        elif part.data is not None:
            chunks.append(json.dumps(part.data, sort_keys=True))
    return "\n".join(chunks)


def build_messages(request: LLMRequest, names: WireNames | None = None) -> list[MessageParam]:
    """Items as Messages API messages, consecutive same-role items merged."""
    names = names or WireNames(request.tools)
    messages: list[tuple[str, list[JsonObject]]] = []

    def push(role: str, block: JsonObject) -> None:
        if messages and messages[-1][0] == role:
            messages[-1][1].append(block)
        else:
            messages.append((role, [block]))

    for item in request.input:
        if isinstance(item, MessageItem):
            role = "user" if item.role is Role.USER else "assistant"
            push(role, {"type": "text", "text": item.text})
        elif isinstance(item, ToolCallItem):
            push(
                "assistant",
                {
                    "type": "tool_use",
                    "id": item.call.call_id,
                    "name": names.encode(item.call.name),
                    "input": cast(JsonValue, item.call.arguments),
                },
            )
        else:
            push(
                "user",
                {
                    "type": "tool_result",
                    "tool_use_id": item.result.call_id,
                    "content": _result_text(item.result.content),
                    "is_error": item.result.is_error,
                },
            )
    return [cast(MessageParam, {"role": role, "content": blocks}) for role, blocks in messages]


def build_tools(
    tools: Sequence[ToolDefinition], names: WireNames | None = None
) -> list[JsonObject]:
    names = names or WireNames(tools)
    return [
        {
            "name": names.encode(t.name),
            "description": names.description(t),
            "input_schema": cast(JsonValue, t.input_schema),
        }
        for t in tools
    ]


def build_params(
    request: LLMRequest, *, model: str, max_tokens: int, names: WireNames | None = None
) -> JsonObject:
    names = names or WireNames(request.tools)
    params: JsonObject = {
        "model": model,
        "max_tokens": request.max_output_tokens or max_tokens,
        "system": [
            {"type": "text", "text": request.instructions, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": cast(JsonValue, build_messages(request, names)),
    }
    if request.tools:
        params["tools"] = cast(JsonValue, build_tools(request.tools, names))
    if request.response_format is not None:
        params["output_config"] = {
            "format": {"type": "json_schema", "schema": cast(JsonValue, request.response_format)}
        }
    return params


def parse_message(message: Message, names: WireNames | None = None) -> LLMResponse:
    names = names or WireNames()
    texts: list[str] = []
    calls: list[ToolCall] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            texts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            raw = cast(object, block.input)
            arguments = (
                cast(JsonObject, raw) if isinstance(raw, dict) else {"value": cast(JsonValue, raw)}
            )
            calls.append(
                ToolCall(call_id=block.id, name=names.decode(block.name), arguments=arguments)
            )
    stop = message.stop_reason
    if stop == "refusal":
        finish = FinishReason.REFUSAL
    elif calls or stop == "tool_use":
        finish = FinishReason.TOOL_CALLS
    elif stop == "max_tokens":
        finish = FinishReason.LENGTH
    else:
        finish = FinishReason.STOP
    cached = message.usage.cache_read_input_tokens or 0
    return LLMResponse(
        output_text="".join(texts),
        tool_calls=tuple(calls),
        usage=Usage(
            input_tokens=message.usage.input_tokens + cached,
            cached_tokens=cached,
            output_tokens=message.usage.output_tokens,
        ),
        model=message.model,
        finish=finish,
    )


def translate_error(exc: Exception) -> Exception:
    if isinstance(exc, anthropic.RateLimitError | anthropic.InternalServerError):
        return RetryableProviderError(str(exc), provider=PROVIDER, status=exc.status_code)
    if isinstance(exc, anthropic.APIConnectionError | anthropic.APITimeoutError):
        return RetryableProviderError(str(exc), provider=PROVIDER, status=0)
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == 529:
            return RetryableProviderError(str(exc), provider=PROVIDER, status=529)
        return ProviderError(str(exc), provider=PROVIDER, status=exc.status_code)
    return exc


class AnthropicLLM(LLM):
    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str = "claude-opus-5-5",
        timeout: timedelta = timedelta(seconds=60),
        max_tokens: int = 2_000,
        client: AsyncAnthropic | None = None,
    ) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.LLM, id=f"anthropic/{model}", version=None),
            LLMModelInfo(
                provider=PROVIDER,
                model=model,
                context_window_tokens=CONTEXT_WINDOWS.get(model, 200_000),
                min_cacheable_tokens=1_024,
            ),
        )
        self._model = model
        self._max_tokens = max_tokens
        self._client = client or AsyncAnthropic(
            api_key=api_key.get_secret_value(), timeout=timeout.total_seconds(), max_retries=0
        )

    async def invoke(self, request: LLMRequest) -> LLMResponse:
        names = WireNames(request.tools)
        params = build_params(request, model=self._model, max_tokens=self._max_tokens, names=names)
        try:
            created = await self._client.messages.create(**params)  # type: ignore[arg-type]
            message = cast(Message, created)
        except Exception as exc:
            raise translate_error(exc) from exc
        return parse_message(message, names)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        names = WireNames(request.tools)
        params = build_params(request, model=self._model, max_tokens=self._max_tokens, names=names)
        try:
            async with self._client.messages.stream(**params) as stream:  # type: ignore[arg-type]
                async for text in stream.text_stream:
                    yield LLMStreamEvent(kind="text_delta", text=str(cast(object, text)))
                final_message = cast(Message, await stream.get_final_message())
                final = parse_message(final_message, names)
        except Exception as exc:
            raise translate_error(exc) from exc
        for call in final.tool_calls:
            yield LLMStreamEvent(kind="tool_call", call=call)
        yield LLMStreamEvent(kind="done", response=final)


__all__ = [
    "AnthropicLLM",
    "build_messages",
    "build_params",
    "build_tools",
    "parse_message",
    "translate_error",
]
