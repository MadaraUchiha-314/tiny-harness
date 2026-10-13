"""The delegation example's ``orders`` MCP server (stdio): a read-only order book.

The ledger agent answers from it. It has no tool that changes an order, so a task that
another agent delegates to the ledger cannot refund or ship anything.
"""

from __future__ import annotations

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

ORDERS: dict[str, dict[str, object]] = {
    "48213": {
        "order_id": "48213",
        "item": "Nimbus 900 blender",
        "status": "shipped",
        "carrier": "Harbour Couriers",
        "shipped": "2026-10-10",
        "expected_delivery": "2026-10-14",
    },
    "48377": {
        "order_id": "48377",
        "item": "Nimbus travel cup",
        "status": "refunded",
        "refunded": "2026-10-09",
        "refund_usd": 24.0,
    },
}

server: MCPServer[object] = MCPServer("orders")


@server.tool(
    name="get_order",
    description="Fetch an order by its id: item, status, shipping or refund details.",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def get_order(order_id: str) -> dict[str, object]:
    return ORDERS.get(order_id, {"order_id": order_id, "error": "not found"})


if __name__ == "__main__":
    server.run(transport="stdio")
