"""The OpenAI adapter's Chat Completions mapping (issue-19 R3).

Many OpenAI-compatible servers implement only ``/chat/completions``, so the adapter can
speak it as well as the Responses API. The static prefix becomes the leading ``system``
message; the calls of one turn are grouped into one ``assistant`` message, as Chat
Completions requires. No ``store`` or ``prompt_cache_key`` is sent: neither is part of the
contract compatible servers implement. Fields a server leaves out (usage, a call id) are
read as absent rather than failing the call (R3.4).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from openai.types.chat import ChatCompletion, ChatCompletionChunk
from openai.types.completion_usage import CompletionUsage

from tiny_harness.harness.models.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    MessageItem,
    ToolCallItem,
    Usage,
)
from tiny_harness.harness.models.wire_names import WireNames
from tiny_harness.harness.tools import ContentPart, ToolCall
from tiny_harness.jsontypes import JsonObject, JsonValue


def result_text(parts: Sequence[ContentPart]) -> str:
    """A tool result as the text both wire APIs carry."""
    chunks: list[str] = []
    for part in parts:
        if part.kind == "text" and part.text is not None:
            chunks.append(part.text)
        elif part.data is not None:
            chunks.append(json.dumps(part.data, sort_keys=True))
    return "\n".join(chunks)


def build_messages(request: LLMRequest, names: WireNames | None = None) -> list[JsonObject]:
    """The ``messages`` list: system prefix, turns, grouped tool calls, tool results."""
    names = names or WireNames(request.tools)
    messages: list[JsonObject] = [{"role": "system", "content": request.instructions}]
    calls: list[JsonValue] = []

    def flush() -> None:
        if calls:
            messages.append({"role": "assistant", "content": None, "tool_calls": list(calls)})
            calls.clear()

    for item in request.input:
        if isinstance(item, ToolCallItem):
            calls.append(
                {
                    "id": item.call.call_id,
                    "type": "function",
                    "function": {
                        "name": names.encode(item.call.name),
                        "arguments": json.dumps(item.call.arguments),
                    },
                }
            )
            continue
        flush()
        if isinstance(item, MessageItem):
            messages.append({"role": item.role.value, "content": item.text})
        else:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.result.call_id,
                    "content": result_text(item.result.content),
                }
            )
    flush()
    return messages


def build_chat_params(
    request: LLMRequest, *, model: str, max_output_tokens: int, names: WireNames | None = None
) -> JsonObject:
    names = names or WireNames(request.tools)
    params: JsonObject = {
        "model": model,
        "messages": cast(JsonValue, build_messages(request, names)),
        "max_tokens": request.max_output_tokens or max_output_tokens,
    }
    if request.tools:
        params["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": names.encode(t.name),
                    "description": names.description(t),
                    "parameters": cast(JsonValue, t.input_schema),
                    "strict": False,
                },
            }
            for t in request.tools
        ]
    if request.response_format is not None:
        params["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "schema": cast(JsonValue, request.response_format),
                "strict": True,
            },
        }
    return params


def _arguments(raw: str | None) -> JsonObject:
    arguments = cast(object, json.loads(raw or "{}"))
    if not isinstance(arguments, dict):
        return {"value": cast(JsonValue, arguments)}
    return cast(JsonObject, arguments)


def _usage(usage: CompletionUsage | None) -> Usage:
    if usage is None:
        return Usage(input_tokens=0, cached_tokens=0, output_tokens=0)
    details = usage.prompt_tokens_details
    return Usage(
        input_tokens=usage.prompt_tokens or 0,
        cached_tokens=(details.cached_tokens or 0) if details is not None else 0,
        output_tokens=usage.completion_tokens or 0,
    )


def finish_reason(*, refused: bool, calls: bool, reason: str | None) -> FinishReason:
    """Refusal, then calls, then length, else stop — calls are judged by presence, since
    some servers report ``stop`` on a turn that called tools."""
    if refused or reason == "content_filter":
        return FinishReason.REFUSAL
    if calls:
        return FinishReason.TOOL_CALLS
    if reason == "length":
        return FinishReason.LENGTH
    return FinishReason.STOP


def parse_chat(completion: ChatCompletion, names: WireNames | None = None) -> LLMResponse:
    names = names or WireNames()
    choice = completion.choices[0]  # IndexError on an empty choices list: unparseable
    message = choice.message
    refused = message.refusal is not None
    text = message.refusal if message.refusal is not None else (message.content or "")
    calls = tuple(
        ToolCall(
            call_id=call.id or f"call_{index}",
            name=names.decode(call.function.name),
            arguments=_arguments(call.function.arguments),
        )
        for index, call in enumerate(message.tool_calls or ())
        if call.type == "function"
    )
    return LLMResponse(
        output_text=text,
        tool_calls=calls,
        usage=_usage(completion.usage),
        model=completion.model,
        finish=finish_reason(refused=refused, calls=bool(calls), reason=choice.finish_reason),
    )


@dataclass
class _PartialCall:
    call_id: str | None = None
    name: str = ""
    arguments: list[str] = field(default_factory=lambda: list[str]())


@dataclass
class ChatStreamAssembler:
    """Turns ``stream=True`` chunks into the adapter's stream events.

    Text is yielded as it arrives; tool-call fragments are accumulated by ``index`` and
    yielded once the stream ends, followed by ``done`` with the assembled response —
    Chat Completions marks no single call as finished.
    """

    names: WireNames
    model: str
    _text: list[str] = field(default_factory=lambda: list[str]())
    _refusal: list[str] = field(default_factory=lambda: list[str]())
    _calls: dict[int, _PartialCall] = field(default_factory=lambda: dict[int, _PartialCall]())
    _reason: str | None = None
    _usage: CompletionUsage | None = None

    def feed(self, chunk: ChatCompletionChunk) -> Sequence[LLMStreamEvent]:
        self.model = chunk.model or self.model
        if chunk.usage is not None:
            self._usage = chunk.usage
        events: list[LLMStreamEvent] = []
        for choice in chunk.choices:
            delta = choice.delta
            if delta.content:
                self._text.append(delta.content)
                events.append(LLMStreamEvent(kind="text_delta", text=delta.content))
            if delta.refusal:
                self._refusal.append(delta.refusal)
            for fragment in delta.tool_calls or ():
                partial = self._calls.setdefault(fragment.index, _PartialCall())
                if fragment.id:
                    partial.call_id = fragment.id
                if fragment.function is not None:
                    partial.name += fragment.function.name or ""
                    partial.arguments.append(fragment.function.arguments or "")
            if choice.finish_reason is not None:
                self._reason = choice.finish_reason
        return events

    def finish(self) -> Sequence[LLMStreamEvent]:
        calls = tuple(
            ToolCall(
                call_id=partial.call_id or f"call_{index}",
                name=self.names.decode(partial.name),
                arguments=_arguments("".join(partial.arguments)),
            )
            for index, partial in sorted(self._calls.items())
        )
        refused = bool(self._refusal)
        response = LLMResponse(
            output_text="".join(self._refusal) if refused else "".join(self._text),
            tool_calls=calls,
            usage=_usage(self._usage),
            model=self.model,
            finish=finish_reason(refused=refused, calls=bool(calls), reason=self._reason),
        )
        events = [LLMStreamEvent(kind="tool_call", call=call) for call in calls]
        events.append(LLMStreamEvent(kind="done", response=response))
        return events


__all__ = [
    "ChatStreamAssembler",
    "build_chat_params",
    "build_messages",
    "finish_reason",
    "parse_chat",
    "result_text",
]
