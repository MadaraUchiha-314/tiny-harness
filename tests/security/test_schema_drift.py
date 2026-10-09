"""Abuse case 8: a tool whose schema changed since registration is not invoked."""

from __future__ import annotations

import pytest

from tests.fixtures.mcp_orders import build
from tiny_harness.errors import ToolSchemaChangedError
from tiny_harness.harness.tools import ToolCall, ToolResult
from tiny_harness.harness.tools.mcp import McpToolSource


async def test_schema_drift_refuses_invoke() -> None:
    versions = [1]
    source = McpToolSource("orders", lambda: build(versions[0]))
    tools = {t.definition.name: t for t in await source.tools()}
    get_order = tools["orders.get_order"]
    call = ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})

    source.begin_iteration()
    assert isinstance(await get_order.invoke(call), ToolResult), "unchanged schema: invoked"

    versions[0] = 2  # the server now advertises a different input schema for get_order
    source.begin_iteration()
    with pytest.raises(ToolSchemaChangedError):
        await get_order.invoke(call)
    assert source.changed == {"get_order"}
    # refund did not change and still works in the same iteration
    refund = tools["orders.refund"]
    out = await refund.invoke(
        ToolCall(call_id="c2", name="orders.refund", arguments={"order_id": "1", "amount": 1.0})
    )
    assert isinstance(out, ToolResult)
    # re-registration clears the refusal and records the new schema
    old_hash = get_order.schema_hash
    tools = {t.definition.name: t for t in await source.tools()}
    assert source.changed == frozenset()
    assert tools["orders.get_order"].schema_hash != old_hash
    assert "customer_id" in str(tools["orders.get_order"].definition.input_schema)
