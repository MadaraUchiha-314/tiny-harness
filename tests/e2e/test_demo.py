"""Feature: the demo
Requirement: docs/specs/issue-3/requirements.md#R24

One harness instance on Temporal Cloud with ``gpt-6.1-sol``: the task plans, calls the
demo's MCP tools, renders an A2UI card, asks the reporter, takes the card's action and
the reply, and reaches a terminal state. Evidence (transcript, final task, trace, ledger)
is written redacted to ``TINY_HARNESS_E2E_EVIDENCE`` when set.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import cast

import pytest
import pytest_asyncio
from a2a.types import TaskState

from tests.e2e.demo import Demo, Driver
from tiny_harness.harness.core import TASK_EXT_KEY
from tiny_harness.interaction.a2ui import BASIC_CATALOG_ID
from tiny_harness.jsontypes import JsonObject

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def demo() -> AsyncIterator[Demo]:
    instance = Demo.create("demo")
    await instance.start_server(with_worker=True)
    try:
        yield instance
    finally:
        instance.stop()


async def test_the_demo_task_runs_to_a_terminal_state_through_both_surfaces(demo: Demo) -> None:
    """
    Feature: the demo
    Requirement: docs/specs/issue-3/requirements.md#R24

    Scenario: the demo task runs to a terminal state
        Given the demo server and worker on Temporal Cloud with the demo plugin
        When the reporter sends the complaint, confirms the card and answers the questions
        Then the task streams SUBMITTED, WORKING, an A2UI artifact and INPUT_REQUIRED
        And the orders MCP server was read, a non-idempotent tool ran at most once
        And the task completes with one chat span per turn in the trace, no secret in it
    """
    driver = Driver(demo)
    try:
        state = await driver.run(on_event=lambda e: print(e.line()))
        final = await driver.final_task()
    finally:
        await driver.close()
    demo.write_evidence("transcript.txt", driver.transcript())
    demo.write_evidence("final-task.json", json.dumps(final, indent=2))
    demo.write_evidence("trace.jsonl", demo.trace_file.read_text())
    demo.write_evidence("orders-ledger.jsonl", demo.ledger_file.read_text())

    kinds = [(e.kind, e.state) for e in driver.events]
    assert kinds[0] == ("task", TaskState.TASK_STATE_SUBMITTED)
    assert ("status_update", TaskState.TASK_STATE_WORKING) in kinds
    assert ("status_update", TaskState.TASK_STATE_INPUT_REQUIRED) in kinds
    assert any(e.kind == "artifact_update" and e.text == "a2ui" for e in driver.events)
    surfaces = [
        cast(JsonObject, p["createSurface"]) for p in driver.a2ui_parts if "createSurface" in p
    ]
    assert any(s.get("catalogId") == BASIC_CATALOG_ID for s in surfaces)
    assert state == TaskState.TASK_STATE_COMPLETED, driver.transcript()
    assert TASK_EXT_KEY in cast(JsonObject, final["metadata"])

    tools = [row["tool"] for row in demo.ledger()]
    assert "get_order" in tools
    assert tools.count("ship_replacement") <= 1 and tools.count("refund") <= 1

    spans = demo.spans()
    chats = [s for s in spans if s["name"] == "chat gpt-6.1-sol"]
    llm_runs = [s for s in spans if s["name"] == "RunActivity:invoke_llm"]
    assert chats and len(chats) == len(llm_runs), (len(chats), len(llm_runs))
    assert any(s["name"] == "execute_tool demo-support/orders.get_order" for s in spans)
    cached = [
        cast(int, cast(JsonObject, s["attributes"]).get("gen_ai.usage.cache_read.input_tokens", 0))
        for s in chats
    ]
    assert any(n > 0 for n in cached[1:]), cached  # the static prefix is cached from turn two
    text = demo.trace_file.read_text() + demo.read_log("server.log")
    for name in ("OPENAI_API_KEY", "TEMPORAL_API_KEY", "TINY_HARNESS_PUSH_KEY"):
        assert os.environ[name] not in text, f"{name} leaked into the trace or log"
