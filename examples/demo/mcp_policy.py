"""The demo's ``policy`` MCP server (stdio): the shop's customer-service policies."""

from __future__ import annotations

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

POLICIES: dict[str, str] = {
    "damaged on arrival": (
        "Within 14 days of delivery the customer may choose a refund or a replacement. "
        "A refund for an item over $75 needs a photo of the damage first; a replacement "
        "can ship without one. Ask the customer which they prefer before acting."
    ),
    "late delivery": "Offer a 10% credit when delivery is more than 5 days late.",
    "warranty": "Manufacturing defects are covered for 12 months from delivery.",
}

server: MCPServer[object] = MCPServer("policy")


@server.tool(
    name="lookup",
    description="Look up the customer-service policy for a topic (e.g. 'damaged on arrival').",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
)
def lookup(topic: str) -> dict[str, str]:
    key = topic.strip().lower()
    for name, text in POLICIES.items():
        if name in key or key in name:
            return {"topic": name, "policy": text}
    return {"topic": key, "policy": "no policy on file; escalate to a human"}


if __name__ == "__main__":
    server.run(transport="stdio")
