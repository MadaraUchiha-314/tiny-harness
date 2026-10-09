"""Feature: MCP tools
Requirement: docs/specs/issue-3/requirements.md#R6

Tools come from MCP servers through the official SDK, with their schemas and annotations.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mcp import StdioServerParameters

from tests.fixtures.mcp_orders import build
from tiny_harness.harness.entities import Registry, RegistryEntry
from tiny_harness.harness.tools import Idempotency, ToolCall, ToolInvoker, ToolResult
from tiny_harness.harness.tools.mcp import McpToolSource

REPO = Path(__file__).resolve().parents[3]


async def test_a_stdio_mcp_servers_tools_are_registered_with_their_schemas() -> None:
    """
    Feature: MCP tools
    Requirement: docs/specs/issue-3/requirements.md#R6

    Scenario: a stdio MCP server's tools are registered with their schemas
        Given the fixture orders server started over stdio
        When the tool source lists it
        Then orders.get_order is idempotent (read-only annotation) and orders.refund is not
        And each tool carries the server's input schema
        And invoking orders.get_order through the validating invoker returns the order
    """
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "tests.fixtures.mcp_orders"], cwd=str(REPO)
    )
    source = McpToolSource("orders", params, version="1.0.0")
    tools = {t.definition.name: t for t in await source.tools()}
    assert set(tools) == {"orders.get_order", "orders.refund"}
    assert tools["orders.get_order"].definition.idempotency is Idempotency.IDEMPOTENT
    assert tools["orders.refund"].definition.idempotency is Idempotency.NOT_IDEMPOTENT
    schema = tools["orders.get_order"].definition.input_schema
    assert "order_id" in str(schema)
    registry = Registry()
    for tool in tools.values():
        await registry.add(RegistryEntry(ref=tool.ref, instance=tool))
    result = await ToolInvoker(registry).invoke(
        ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})
    )
    assert isinstance(result, ToolResult) and not result.is_error
    assert any(
        p.kind == "data" and p.data and p.data.get("item") == "blender" for p in result.content
    )
    bad = await ToolInvoker(registry).invoke(
        ToolCall(call_id="c2", name="orders.get_order", arguments={"order": "x"})
    )
    assert isinstance(bad, ToolResult) and bad.is_error


async def test_an_in_process_server_round_trips_text_results() -> None:
    """
    Feature: MCP tools
    Requirement: docs/specs/issue-3/requirements.md#R6

    Scenario: a tool's text result is returned untrusted
        Given the fixture orders server in process
        When orders.refund is invoked
        Then the text result comes back marked untrusted
    """
    source = McpToolSource("orders", build())
    tools = {t.definition.name: t for t in await source.tools()}
    result = await tools["orders.refund"].invoke(
        ToolCall(
            call_id="c3", name="orders.refund", arguments={"order_id": "48213", "amount": 129.0}
        )
    )
    assert isinstance(result, ToolResult) and result.untrusted is True
    assert result.content[0].text == "refunded 129.0 on 48213"
