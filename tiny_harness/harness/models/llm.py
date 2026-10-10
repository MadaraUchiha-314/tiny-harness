"""The LLM model entity (R18.1, R18.6): one interface over the providers' SDKs.

A request is the static prefix (``instructions``), the per-turn ``input`` items, the tool
definitions and an optional structured-output schema. A response carries the text, the
tool calls the model emitted (the only way text becomes an action), the usage including
cached tokens, and the finish reason. ``FakeLLM`` is the scripted implementation tests
use; the OpenAI and Anthropic adapters live beside it.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from tiny_harness.harness.entities import Entity, EntityKind, EntityRef
from tiny_harness.harness.tools.models import ToolCall, ToolDefinition, ToolResult
from tiny_harness.jsontypes import JsonSchema


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageItem(BaseModel, frozen=True):
    kind: Literal["message"] = "message"
    role: Role
    text: str


class ToolCallItem(BaseModel, frozen=True):
    """A call the assistant made on an earlier turn, replayed into the input."""

    kind: Literal["tool_call"] = "tool_call"
    call: ToolCall


class ToolResultItem(BaseModel, frozen=True):
    kind: Literal["tool_result"] = "tool_result"
    result: ToolResult


type InputItem = MessageItem | ToolCallItem | ToolResultItem


class LLMRequest(BaseModel, frozen=True):
    instructions: str
    input: tuple[InputItem, ...]
    tools: tuple[ToolDefinition, ...] = ()
    response_format: JsonSchema | None = None
    cache_key: str | None = None
    max_output_tokens: int | None = None


class Usage(BaseModel, frozen=True):
    input_tokens: int
    cached_tokens: int
    output_tokens: int


class FinishReason(StrEnum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    REFUSAL = "refusal"


class LLMResponse(BaseModel, frozen=True):
    output_text: str
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    model: str
    finish: FinishReason


class LLMStreamEvent(BaseModel, frozen=True):
    """A streaming increment: text delta, a completed tool call, or the final response."""

    kind: Literal["text_delta", "tool_call", "done"]
    text: str | None = None
    call: ToolCall | None = None
    response: LLMResponse | None = None


class LLMModelInfo(BaseModel, frozen=True):
    provider: str
    model: str
    context_window_tokens: int
    min_cacheable_tokens: int = 0


class LLM(Entity):
    """The model entity: ``invoke`` for one turn, ``stream`` for incremental output."""

    kind = EntityKind.LLM

    def __init__(self, ref: EntityRef, info: LLMModelInfo) -> None:
        super().__init__(ref)
        self.info = info

    @abstractmethod
    async def invoke(self, request: LLMRequest) -> LLMResponse: ...

    @abstractmethod
    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]: ...


def extract_tool_calls(response: LLMResponse) -> tuple[ToolCall, ...]:
    """The pure function the loop uses: calls come only from ``tool_calls``, never from the
    text (abuse case 2)."""
    return response.tool_calls


class FakeLLM(LLM):
    """Returns scripted responses in order; records every request it saw."""

    def __init__(self, responses: Sequence[LLMResponse], *, model: str = "fake-1") -> None:
        super().__init__(
            EntityRef(kind=EntityKind.LLM, id="fake", version=None),
            LLMModelInfo(provider="fake", model=model, context_window_tokens=128_000),
        )
        self._responses = list(responses)
        self.requests: list[LLMRequest] = []

    async def invoke(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("FakeLLM has no scripted response left")
        return self._responses.pop(0)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        response = await self.invoke(request)
        if response.output_text:
            yield LLMStreamEvent(kind="text_delta", text=response.output_text)
        for call in response.tool_calls:
            yield LLMStreamEvent(kind="tool_call", call=call)
        yield LLMStreamEvent(kind="done", response=response)


def scripted(
    text: str = "",
    *,
    tool_calls: Sequence[ToolCall] = (),
    input_tokens: int = 100,
    cached_tokens: int = 0,
    output_tokens: int = 10,
    model: str = "fake-1",
) -> LLMResponse:
    """A response for scripts and tests."""
    return LLMResponse(
        output_text=text,
        tool_calls=tuple(tool_calls),
        usage=Usage(
            input_tokens=input_tokens, cached_tokens=cached_tokens, output_tokens=output_tokens
        ),
        model=model,
        finish=FinishReason.TOOL_CALLS if tool_calls else FinishReason.STOP,
    )


__all__ = [
    "LLM",
    "FakeLLM",
    "FinishReason",
    "InputItem",
    "LLMModelInfo",
    "LLMRequest",
    "LLMResponse",
    "LLMStreamEvent",
    "MessageItem",
    "Role",
    "ToolCallItem",
    "ToolResultItem",
    "Usage",
    "extract_tool_calls",
    "scripted",
]
