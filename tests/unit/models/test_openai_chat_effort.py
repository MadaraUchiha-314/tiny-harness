"""The Chat Completions adapter's per-request model and effort (issue-25 R7.3, R8.3, R8.5)."""

from __future__ import annotations

import json
from typing import cast

import httpx2

from tests.unit.models.test_openai_chat import answering, llm, request
from tiny_harness.harness.models.openai_chat import build_chat_params

JsonObject = dict[str, object]


def test_an_unset_effort_sends_no_reasoning_effort() -> None:
    params = build_chat_params(request(), model="qwen3:8b", max_output_tokens=900)
    assert set(params) == {"model", "messages", "max_tokens", "tools"}
    assert params["model"] == "qwen3:8b"


def test_the_effort_maps_to_reasoning_effort_and_the_request_model_wins() -> None:
    req = request().model_copy(update={"model": "qwen3:32b", "reasoning_effort": "low"})
    params = build_chat_params(req, model="qwen3:8b", max_output_tokens=900)
    assert params["reasoning_effort"] == "low"
    assert params["model"] == "qwen3:32b"


async def test_unset_settings_keep_the_wire_bytes_and_a_set_effort_reaches_the_wire() -> None:
    seen: list[httpx2.Request] = []
    adapter = llm(answering("text.json", seen))
    await adapter.invoke(request())
    await adapter.invoke(request().model_copy(update={"model": None, "reasoning_effort": None}))
    await adapter.invoke(request().model_copy(update={"reasoning_effort": "medium"}))
    assert seen[0].content == seen[1].content
    body = cast(JsonObject, json.loads(seen[2].content))
    assert body["reasoning_effort"] == "medium" and body["model"] == "qwen3:8b"
