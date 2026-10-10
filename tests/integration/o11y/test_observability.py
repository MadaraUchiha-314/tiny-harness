"""Feature: Observability
Requirement: docs/specs/issue-3/requirements.md#R17

One span per lifecycle operation, GenAI attributes, context across Temporal and MCP.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from a2a.types import TaskState
from mcp import StdioServerParameters
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from tests.integration.durable.conftest import Harness, env, message, send, start
from tiny_harness.config import O11yConfig
from tiny_harness.harness.entities import RegistryEntry
from tiny_harness.harness.models import scripted
from tiny_harness.harness.plugins import PluginLoader
from tiny_harness.harness.plugins.registrar import RegistryRegistrar
from tiny_harness.harness.tools import ToolCall
from tiny_harness.harness.tools.mcp import McpToolSource
from tiny_harness.service.o11y import configure_tracing, o11y_plugin
from tiny_harness.service.o11y.plugin import executor

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]
REPO = Path(__file__).resolve().parents[3]


def span_id(span: ReadableSpan) -> int:
    context = span.get_span_context()
    assert context is not None
    return context.span_id


def trace_id(span: ReadableSpan) -> int:
    context = span.get_span_context()
    assert context is not None
    return context.trace_id


async def test_one_span_per_operation_with_genai_attributes_crosses_the_workflow_boundary(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Observability
    Requirement: docs/specs/issue-3/requirements.md#R17

    Scenario: one span per operation with GenAI attributes crosses the workflow boundary
        Given the o11y plugin loaded through the plugin loader and an in-memory exporter
        And a worker with Temporal's tracing interceptor and a real stdio MCP tool
        When a task calls the MCP tool and completes
        Then every operation has one span, the LLM span carries GenAI usage attributes
        And the LLM and tool spans descend from Temporal's activity spans of one trace
        And the MCP client span descends from the tool span
    """
    exporter = InMemorySpanExporter()
    provider = configure_tracing(O11yConfig(), exporter=exporter)  # global: MCP uses it too
    executor.provider = provider
    call = ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})
    h = await Harness([scripted("", tool_calls=[call]), scripted("Refunded.")]).bind()
    report = await PluginLoader(
        hook_manager=h.hooks, registrar=RegistryRegistrar(h.registry), data_root=tmp_path
    ).load(o11y_plugin())
    assert [c.id for c in report.loaded] == ["o11y"]
    source = McpToolSource(
        "orders",
        StdioServerParameters(
            command=sys.executable, args=["-m", "tests.fixtures.mcp_orders"], cwd=str(REPO)
        ),
        version="1.0.0",
    )
    for tool in await source.tools():
        await h.registry.add(RegistryEntry(ref=tool.ref, instance=tool), override=True)
    tq = f"tq-{uuid.uuid4().hex[:8]}"
    traced = Client(  # as `connect()` builds it: the client interceptor roots the trace
        env.client.service_client,
        namespace=env.client.namespace,
        data_converter=pydantic_data_converter,
        interceptors=[TracingInterceptor()],
    )
    async with h.worker(traced, tq):
        handle = await send(traced, tq, start(), message("refund 48213", message_id="m1"))
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    spans = exporter.get_finished_spans()
    by_id = {span_id(s): s for s in spans}
    names = [s.name for s in spans]
    assert names.count("chat fake-1") == 2, names
    assert names.count("execute_tool orders.get_order") == 1
    assert "invoke_agent tiny-harness" in names and "RunActivity:persist" in names
    assert names.count("RunActivity:invoke_llm") == 2, names  # one interceptor, not two
    chat = next(s for s in spans if s.name == "chat fake-1")
    assert (chat.attributes or {})["gen_ai.usage.input_tokens"] == 100
    tool_span = next(s for s in spans if s.name == "execute_tool orders.get_order")
    assert tool_span.parent is not None
    parent = by_id[tool_span.parent.span_id]
    assert parent.name.startswith("RunActivity:invoke_tool"), parent.name
    trace_ids = {trace_id(s) for s in (chat, tool_span, parent)}
    assert len(trace_ids) == 1, "the operation spans share the workflow run's trace"
    mcp_spans = [
        s
        for s in spans
        if s.instrumentation_scope is not None and s.instrumentation_scope.name == "mcp-python-sdk"
    ]
    assert mcp_spans, "the MCP SDK emitted a client span"
    tool_span_id = span_id(tool_span)
    assert any(s.parent is not None and s.parent.span_id == tool_span_id for s in mcp_spans), (
        "the MCP span nests under the tool span"
    )
    assert executor.open_spans == 0
