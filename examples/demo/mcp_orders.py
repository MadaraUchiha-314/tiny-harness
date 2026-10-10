"""The demo's ``orders`` MCP server (stdio): the order book of a small shop.

``get_order`` is read-only and idempotent (the harness may retry it); ``refund`` and
``ship_replacement`` are not (a failure is never retried automatically, R19.5).

Every call is appended to ``$PLUGIN_DATA/orders-ledger.jsonl`` (the harness sets
``PLUGIN_DATA``): the shop's audit ledger, which the e2e tests read to prove a
non-idempotent tool ran at most once across a worker crash. While the marker file
``$PLUGIN_DATA/slow-get-order`` exists, ``get_order`` waits before answering, so a test
can kill the worker in the middle of an idempotent tool activity (T12).
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

DATA = Path(os.environ["PLUGIN_DATA"]) if os.environ.get("PLUGIN_DATA") else None
SLOW_MARKER = "slow-get-order"
SLOW_LIMIT_SECONDS = 180.0


def record(tool: str, **arguments: object) -> None:
    if DATA is None:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    row = {"tool": tool, "arguments": arguments, "ts": datetime.now(UTC).isoformat()}
    with (DATA / "orders-ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def wait_while_slow() -> None:
    if DATA is None:
        return
    deadline = time.monotonic() + SLOW_LIMIT_SECONDS
    while (DATA / SLOW_MARKER).exists() and time.monotonic() < deadline:
        time.sleep(0.5)


ORDERS: dict[str, dict[str, object]] = {
    "48213": {
        "order_id": "48213",
        "customer": "cust-7781",
        "item": "Nimbus 900 blender",
        "price_usd": 129.0,
        "ordered": "2026-09-29",
        "delivered": "2026-10-06",
        "warranty": "active until 2027-10-06",
        "shipping_address": "14 Harbour Lane, Portsea",
    },
    "48377": {
        "order_id": "48377",
        "customer": "cust-7781",
        "item": "Nimbus travel cup",
        "price_usd": 24.0,
        "ordered": "2026-10-07",
        "delivered": None,
        "warranty": "active until 2027-10-07",
        "shipping_address": "3 Quay Street, Portsea",
    },
}

server: MCPServer[object] = MCPServer("orders")


@server.tool(
    name="get_order",
    description="Fetch an order by its id: item, price, delivery date, warranty, address.",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def get_order(order_id: str) -> dict[str, object]:
    record("get_order", order_id=order_id)
    wait_while_slow()
    return ORDERS.get(order_id, {"order_id": order_id, "error": "not found"})


@server.tool(
    name="list_open_orders",
    description="List the open orders of the customer who placed the given order.",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def list_open_orders(order_id: str) -> list[dict[str, object]]:
    record("list_open_orders", order_id=order_id)
    order = ORDERS.get(order_id)
    if order is None:
        return []
    customer = order["customer"]
    return [o for o in ORDERS.values() if o["customer"] == customer]


@server.tool(name="refund", description="Issue a refund on an order (not reversible).")
def refund(order_id: str, amount_usd: float, reason: str) -> str:
    record("refund", order_id=order_id, amount_usd=amount_usd, reason=reason)
    return f"refund of ${amount_usd:.2f} issued on order {order_id}: {reason}"


@server.tool(
    name="ship_replacement",
    description="Ship a replacement for an order to the given address (not reversible).",
)
def ship_replacement(order_id: str, address: str) -> str:
    record("ship_replacement", order_id=order_id, address=address)
    return f"replacement for order {order_id} shipping to {address}; tracking NB-{order_id}-R1"


if __name__ == "__main__":
    server.run(transport="stdio")
