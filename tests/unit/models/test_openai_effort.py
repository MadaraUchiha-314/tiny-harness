"""The Responses adapter's per-request model and reasoning effort (issue-25 R7.3, R8.3, R8.5)."""

from __future__ import annotations

import json
from typing import cast

import httpx2
from pydantic import SecretStr

from tests.unit.models.test_openai import client_for, fixture, request
from tiny_harness.harness.models import OpenAILLM
from tiny_harness.harness.models.openai_adapter import build_params

JsonObject = dict[str, object]

BEFORE_KEYS = {"model", "instructions", "input", "store", "max_output_tokens", "tools"}
"""The keys a Responses request carried before per-request settings existed."""


def recording(seen: list[bytes]) -> OpenAILLM:
    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req.content)
        return httpx2.Response(200, json=fixture("response_text.json"))

    return OpenAILLM(SecretStr("sk-test"), model="gpt-6.1-sol", client=client_for(handler))


def test_an_unset_effort_sends_no_reasoning_parameter() -> None:
    params = cast(JsonObject, build_params(request(), model="gpt-6.1-sol", max_output_tokens=900))
    assert set(params) == BEFORE_KEYS | {"prompt_cache_key"}
    assert params["model"] == "gpt-6.1-sol"


def test_the_effort_maps_to_reasoning_effort() -> None:
    req = request().model_copy(update={"reasoning_effort": "high"})
    params = cast(JsonObject, build_params(req, model="gpt-6.1-sol", max_output_tokens=900))
    assert params["reasoning"] == {"effort": "high"}


async def test_the_request_model_overrides_the_adapters_and_unset_is_byte_identical() -> None:
    seen: list[bytes] = []
    llm = recording(seen)
    await llm.invoke(request())
    await llm.invoke(request().model_copy(update={"model": None, "reasoning_effort": None}))
    await llm.invoke(request().model_copy(update={"model": "gpt-6.1-mini"}))
    assert seen[0] == seen[1]  # nothing set: the wire bytes are today's
    first, chosen = (cast(JsonObject, json.loads(b)) for b in (seen[0], seen[2]))
    assert first["model"] == "gpt-6.1-sol" and "reasoning" not in first
    assert chosen["model"] == "gpt-6.1-mini"
