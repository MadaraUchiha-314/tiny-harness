"""Feature: Embedded Temporal mode
Requirement: docs/specs/issue-17/requirements.md#R6

The demo with an embedded Temporal: one ``serve`` process (the worker runs inside it), no
``TEMPORAL_API_KEY`` in its environment, a real model, the demo's MCP tools.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from a2a.types import TaskState

from tests.e2e.demo import SECRET_VARIABLES, Demo, Driver

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def demo() -> AsyncIterator[Demo]:
    instance = Demo.create("embedded", embedded=True)
    try:
        await instance.start_server()  # no --with-worker: embedded mode forces it in-process
        yield instance
    finally:
        instance.stop()


async def test_demo_completes_a_task_in_embedded_mode_without_temporal_credentials(
    demo: Demo,
) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R6

    Scenario: Demo completes a task in embedded mode without Temporal credentials
        Given the demo configured with mode embedded
        And no TEMPORAL_API_KEY in the server's environment
        When the reporter sends the complaint and answers the questions
        Then the task reaches COMPLETED through the in-process worker
        And the server log shows the embedded server's start, its warning, and its stop
        And no secret reached the trace or the log
    """
    assert "TEMPORAL_API_KEY" not in demo.env()
    driver = Driver(demo)
    try:
        state = await driver.run(on_event=lambda e: print(e.line()))
        final = await driver.final_task()
    finally:
        await driver.close()
    demo.write_evidence("embedded-transcript.txt", driver.transcript())
    demo.write_evidence("embedded-final-task.json", json.dumps(final, indent=2))
    assert state == TaskState.TASK_STATE_COMPLETED, driver.transcript()
    log = demo.read_log("server.log")
    assert "embedded Temporal at 127.0.0.1:" in log
    assert "not for production" in log
    assert "embedded mode: the worker runs in this process" in log
    tools = [row["tool"] for row in demo.ledger()]
    assert "get_order" in tools
    text = demo.trace_file.read_text() + log
    for name in SECRET_VARIABLES:
        value = os.environ.get(name)
        assert not value or value not in text, f"{name} leaked into the trace or log"
