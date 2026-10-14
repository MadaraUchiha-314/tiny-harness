"""The agent on every log line and span (issue-36 NFR observability): ``CURRENT_AGENT``
puts an ``agent`` field on JSON log lines and a ``tiny_harness.agent`` attribute on spans,
and the worker interceptor sets it for the length of an activity only."""

from __future__ import annotations

import json
import logging
from typing import cast

from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput

from tiny_harness.service.durable.worker import AgentContextInterceptor
from tiny_harness.service.o11y.logging import CURRENT_AGENT, JsonFormatter


def line(message: str) -> dict[str, object]:
    record = logging.LogRecord("tiny_harness.x", logging.INFO, __file__, 1, message, None, None)
    return cast(dict[str, object], json.loads(JsonFormatter().format(record)))


def test_a_line_names_the_current_agent() -> None:
    token = CURRENT_AGENT.set("billing")
    try:
        assert line("hello")["agent"] == "billing"
    finally:
        CURRENT_AGENT.reset(token)


def test_a_line_outside_any_agent_has_no_agent_field() -> None:
    assert "agent" not in line("hello")


class Inner(ActivityInboundInterceptor):
    def __init__(self) -> None:
        self.seen: str | None = None

    async def execute_activity(self, input: ExecuteActivityInput) -> object:
        self.seen = CURRENT_AGENT.get()
        return "done"


async def test_the_worker_interceptor_sets_the_agent_for_one_activity() -> None:
    inner = Inner()
    wrapped = AgentContextInterceptor("billing").intercept_activity(inner)
    result = await wrapped.execute_activity(cast(ExecuteActivityInput, object()))
    assert (result, inner.seen) == ("done", "billing")
    assert CURRENT_AGENT.get() is None
