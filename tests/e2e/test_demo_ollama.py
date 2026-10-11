"""Feature: OpenAI-compatible endpoints
Requirement: docs/specs/issue-19/requirements.md#R6

The demo fully offline: embedded Temporal, a local Ollama behind ``[openai] base_url`` on
loopback, no ``OPENAI_API_KEY`` and no ``TEMPORAL_API_KEY``. Skips, with the reason, when
no Ollama answers on 127.0.0.1:11434 or the model is not pulled.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import cast

import httpx
import pytest
import pytest_asyncio
from a2a.types import TaskState

from tests.e2e.demo import (
    OLLAMA_MODEL,
    OLLAMA_URL,
    SECRET_VARIABLES,
    Demo,
    Driver,
    ollama_unavailable,
)
from tiny_harness.jsontypes import JsonObject

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]

MODEL = os.environ.get("TINY_HARNESS_OLLAMA_MODEL", OLLAMA_MODEL)


def ollama_tags() -> JsonObject | None:
    try:
        response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return cast(JsonObject, response.json()) if response.is_success else None
    except httpx.HTTPError, ValueError:
        return None


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def demo() -> AsyncIterator[Demo]:
    reason = ollama_unavailable(MODEL, ollama_tags())
    if reason is not None:
        pytest.skip(reason)
    instance = Demo.create("ollama", ollama_model=MODEL)
    try:
        await instance.start_server()
        yield instance
    finally:
        instance.stop()


async def test_demo_completes_a_task_offline_against_a_local_ollama(demo: Demo) -> None:
    """
    Feature: OpenAI-compatible endpoints
    Requirement: docs/specs/issue-19/requirements.md#R6

    Scenario: Demo completes a task offline against a local Ollama
        Given the demo configured with mode embedded and base_url a loopback Ollama
        And neither OPENAI_API_KEY nor TEMPORAL_API_KEY in the server's environment
        When the reporter sends the complaint and answers the questions
        Then the task reaches COMPLETED
        And the server log names the loopback endpoint and the chat_completions API
        And no secret reached the trace or the log
    """
    env = demo.env()
    assert "OPENAI_API_KEY" not in env and "TEMPORAL_API_KEY" not in env
    driver = Driver(demo)
    try:
        state = await driver.run(on_event=lambda e: print(e.line()))
        final = await driver.final_task()
    finally:
        await driver.close()
    demo.write_evidence("ollama-transcript.txt", driver.transcript())
    demo.write_evidence("ollama-final-task.json", json.dumps(final, indent=2))
    assert state == TaskState.TASK_STATE_COMPLETED, driver.transcript()
    log = demo.read_log("server.log")
    assert f"model endpoint {OLLAMA_URL} api=chat_completions model={MODEL}" in log
    text = demo.trace_file.read_text() + log
    for name in SECRET_VARIABLES:
        value = os.environ.get(name)
        assert not value or value not in text, f"{name} leaked into the trace or log"
