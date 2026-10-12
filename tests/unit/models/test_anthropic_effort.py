"""The Anthropic adapter's per-request model and effort (issue-25 R7.3, R8.3, R8.5)."""

from __future__ import annotations

import json
from typing import cast

import httpx2

from tests.unit.models.test_anthropic import fixture, llm, request
from tiny_harness.harness.models.anthropic_adapter import build_params

JsonObject = dict[str, object]


def test_an_unset_effort_sends_no_output_config() -> None:
    params = build_params(request(), model="claude-opus-5-5", max_tokens=2_000)
    assert set(params) == {"model", "max_tokens", "system", "messages", "tools"}


def test_the_effort_maps_to_output_config_and_keeps_a_response_format() -> None:
    req = request().model_copy(
        update={
            "model": "claude-fable-5-1",
            "reasoning_effort": "high",
            "response_format": {"type": "object"},
        }
    )
    params = build_params(req, model="claude-opus-5-5", max_tokens=2_000)
    assert params["model"] == "claude-fable-5-1"
    config = cast(JsonObject, params["output_config"])
    assert config["effort"] == "high"
    assert config["format"] == {"type": "json_schema", "schema": {"type": "object"}}


async def test_unset_settings_keep_the_wire_bytes_and_the_request_model_reaches_the_wire() -> None:
    seen: list[bytes] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req.content)
        return httpx2.Response(200, json=fixture("message_text.json"))

    adapter = llm(handler)
    await adapter.invoke(request())
    await adapter.invoke(request().model_copy(update={"model": None, "reasoning_effort": None}))
    await adapter.invoke(
        request().model_copy(update={"model": "claude-fable-5-1", "reasoning_effort": "low"})
    )
    assert seen[0] == seen[1]
    body = cast(JsonObject, json.loads(seen[2]))
    assert body["model"] == "claude-fable-5-1"
    assert body["output_config"] == {"effort": "low"}
