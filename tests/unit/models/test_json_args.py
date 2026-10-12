"""Tool-call arguments are refused past a fixed nesting depth, whatever the C stack
allows (issue-19 abuse case 4; CI runners run with an unlimited stack, where
``json.loads`` parses a 100 000-deep array and the error message then takes minutes)."""

from __future__ import annotations

import json
import time
from typing import cast

import httpx2
import pytest

from tests.unit.models.test_openai_chat import fixture
from tests.unit.models.test_openai_chat import llm as chat_llm
from tests.unit.models.test_openai_chat import request as chat_request
from tests.unit.models.test_openai_malformed import llm, request, tool_call_body
from tiny_harness.errors import ProviderError
from tiny_harness.harness.models.json_args import MAX_DEPTH, loads_arguments, nesting_depth

JsonObject = dict[str, object]
OVER = "[" * (MAX_DEPTH + 1) + "]" * (MAX_DEPTH + 1)  # parses fine with json.loads


def test_nesting_depth_ignores_brackets_inside_strings() -> None:
    """
    Feature: Bounded tool-call arguments
    Scenario: depth counts structure, not string contents
        Given arguments whose strings contain brackets and escaped quotes
        When their nesting depth is measured
        Then only the object and array nesting counts
    """
    assert nesting_depth('{"a": "[[[{{{", "b": [1, {"c": "\\"]]"}]}') == 3
    assert nesting_depth("") == 0


def test_over_deep_arguments_are_refused_without_echoing_them() -> None:
    """
    Feature: Bounded tool-call arguments
    Scenario: a body past the depth limit is refused before parsing
        Given arguments nested one level past the limit and 100 000 levels deep
        When they are loaded
        Then each is a ValueError naming the limit, raised at once, not the body
    """
    for raw in (OVER, "[" * 100_000 + "]" * 100_000):
        started = time.monotonic()
        with pytest.raises(ValueError, match=f"deeper than {MAX_DEPTH}") as caught:
            loads_arguments(raw)
        assert time.monotonic() - started < 5
        assert "[[[" not in str(caught.value)


def test_arguments_at_the_limit_and_empty_arguments_load() -> None:
    """
    Feature: Bounded tool-call arguments
    Scenario: ordinary arguments are unaffected
        Given arguments exactly at the depth limit, and empty arguments
        When they are loaded
        Then they parse as json.loads would, and empty is {}
    """
    at = "[" * MAX_DEPTH + "]" * MAX_DEPTH
    assert loads_arguments(at) == json.loads(at)
    assert loads_arguments(None) == {} and loads_arguments("") == {}


async def test_abuse_responses_api_refuses_over_deep_arguments() -> None:
    """
    Feature: Bounded tool-call arguments
    Scenario: the Responses mapping refuses arguments past the limit
        Given a tool call whose arguments nest one level past the limit
        When the model is invoked
        Then the call is a ProviderError, though json.loads alone would accept it
    """
    body = tool_call_body()
    cast(list[JsonObject], body["output"])[1]["arguments"] = OVER
    with pytest.raises(ProviderError, match="deeper than"):
        await llm(lambda _: httpx2.Response(200, json=body)).invoke(request())


async def test_abuse_chat_completions_refuses_over_deep_arguments() -> None:
    """
    Feature: Bounded tool-call arguments
    Scenario: the Chat Completions mapping refuses arguments past the limit
        Given a chat tool call whose arguments nest one level past the limit
        When the model is invoked
        Then the call is a ProviderError, though json.loads alone would accept it
    """
    body = fixture("tool_calls.json")
    choices = cast(list[JsonObject], body["choices"])
    message = cast(JsonObject, choices[0]["message"])
    calls = cast(list[JsonObject], message["tool_calls"])
    cast(JsonObject, calls[0]["function"])["arguments"] = OVER
    with pytest.raises(ProviderError, match="deeper than"):
        await chat_llm(lambda _: httpx2.Response(200, json=body)).invoke(chat_request())
