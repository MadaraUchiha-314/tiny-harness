"""The fixture MCP server ``orders``: one read-only tool, one side-effecting tool.

Run as a stdio server with ``python -m tests.fixtures.mcp_orders``; tests also pass the
``server`` object in-process. ``build(version)`` returns a server whose ``get_order``
schema differs by version, for the schema-drift test.
"""

from __future__ import annotations

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

ORDERS: dict[str, dict[str, object]] = {
    "48213": {"order_id": "48213", "item": "blender", "delivered": "2026-10-06", "warranty": True},
}


def build(version: int = 1) -> MCPServer[object]:
    server: MCPServer[object] = MCPServer("orders")

    if version == 1:

        @server.tool(
            name="get_order",
            description="Fetch an order by id",
            annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
        )
        def get_order(order_id: str) -> dict[str, object]:
            return ORDERS.get(order_id, {"order_id": order_id, "error": "not found"})

    else:

        @server.tool(
            name="get_order",
            description="Fetch an order by id (v2 takes a customer id too)",
            annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
        )
        def get_order_v2(order_id: str, customer_id: str) -> dict[str, object]:
            return ORDERS.get(order_id, {"order_id": order_id, "error": "not found"})

    @server.tool(name="refund", description="Issue a refund")
    def refund(order_id: str, amount: float) -> str:
        return f"refunded {amount} on {order_id}"

    return server


server = build()

if __name__ == "__main__":
    server.run(transport="stdio")
