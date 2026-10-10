"""Feature: Plugins
Requirement: docs/specs/issue-3/requirements.md#R5

A loaded skill's tools appear and disappear with load and unload (R5.3, R5.6).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tiny_harness.harness.entities import EntityKind, Registry, RegistryEntry
from tiny_harness.harness.skills import SkillLoader
from tiny_harness.harness.tools import ToolCall, ToolInvoker, ToolResult, WorkflowCommand
from tiny_harness.harness.tools.skill_tools import SkillSession, skill_tools

REPO = Path(__file__).resolve().parents[3]


def make_skill(root: Path) -> Path:
    directory = root / "orders-support"
    (directory / "references").mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        "---\nname: orders-support\ndescription: Look up orders before answering.\n---\n\n"
        "# Orders support\n\nAlways fetch the order first.\n"
    )
    (directory / "references" / "policy.md").write_text("Refund within 14 days.")
    (directory / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                "mcpServers": {
                    "orders": {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": ["-m", "tests.fixtures.mcp_orders"],
                        "cwd": "./",
                        "env": {"PYTHONPATH": str(REPO)},
                    }
                },
            }
        )
    )
    return directory


async def test_a_loaded_skills_mcp_tools_appear_and_disappear_with_load_and_unload(
    tmp_path: Path,
) -> None:
    """
    Feature: Plugins
    Requirement: docs/specs/issue-3/requirements.md#R5

    Scenario: a loaded skill's MCP tools appear and disappear with load and unload
        Given a registered skill whose mcp.json declares the orders server
        When the LLM calls list_skills, then load_skill
        Then the skill's body comes back as the result and a skill_loaded command names
             the orders tools, which are now registered and invokable
        And load_skill_resource returns a reference, and unload_skill removes the tools
    """
    registry = Registry()
    skill = SkillLoader().load(make_skill(tmp_path), version="1.0.0")
    await registry.add(RegistryEntry(ref=skill.ref, instance=skill))
    session = SkillSession(registry, data_root=tmp_path / "data")
    for tool in skill_tools(session):
        await registry.add(RegistryEntry(ref=tool.ref, instance=tool))
    invoker = ToolInvoker(registry)

    listed = await invoker.invoke(ToolCall(call_id="c1", name="list_skills", arguments={}))
    assert isinstance(listed, ToolResult) and "orders-support: Look up orders" in (
        listed.content[0].text or ""
    )

    loaded = await invoker.invoke(
        ToolCall(call_id="c2", name="load_skill", arguments={"name": "orders-support"})
    )
    assert isinstance(loaded, WorkflowCommand) and loaded.kind == "skill_loaded"
    assert loaded.payload["tools"] == [
        "orders-support.orders.get_order",
        "orders-support.orders.refund",
    ]
    assert "Always fetch the order first" in (loaded.result.content[0].text or "")
    tool_ids = {r.id for r in registry.list(EntityKind.TOOL)}
    assert "orders-support.orders.get_order" in tool_ids

    fetched = await invoker.invoke(
        ToolCall(
            call_id="c3", name="orders-support.orders.get_order", arguments={"order_id": "48213"}
        )
    )
    assert isinstance(fetched, ToolResult) and not fetched.is_error

    resource = await invoker.invoke(
        ToolCall(
            call_id="c4",
            name="load_skill_resource",
            arguments={"name": "orders-support", "kind": "references", "resource": "policy.md"},
        )
    )
    assert isinstance(resource, ToolResult) and resource.content[0].text == "Refund within 14 days."

    unloaded = await invoker.invoke(
        ToolCall(call_id="c5", name="unload_skill", arguments={"name": "orders-support"})
    )
    assert isinstance(unloaded, WorkflowCommand) and unloaded.kind == "skill_unloaded"
    assert "orders-support.orders.get_order" not in {r.id for r in registry.list(EntityKind.TOOL)}
    gone = await invoker.invoke(
        ToolCall(
            call_id="c6", name="orders-support.orders.get_order", arguments={"order_id": "48213"}
        )
    )
    assert isinstance(gone, ToolResult) and gone.is_error

    missing = await invoker.invoke(
        ToolCall(call_id="c7", name="load_skill", arguments={"name": "nope"})
    )
    assert isinstance(missing, ToolResult) and missing.is_error
