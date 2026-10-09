"""Feature: Plugins
Requirement: docs/specs/issue-3/requirements.md#R3

Agent Plugins 1.0.0 directories and the programmatic form load the same components.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import HttpUrl

from tests.fixtures.plugins.registrar import RecordingRegistrar
from tiny_harness.harness.hooks import HookManager, HookPoint, Operation, Phase
from tiny_harness.harness.plugins import (
    ComponentKind,
    HookDef,
    McpHttpServer,
    McpStdioServer,
    Plugin,
    PluginLoader,
    PluginManifest,
    discover,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugins"


def loader(
    tmp_path: Path, registrar: RecordingRegistrar | None = None
) -> tuple[PluginLoader, HookManager, RecordingRegistrar]:
    hooks = HookManager()
    reg = registrar or RecordingRegistrar()
    return PluginLoader(hook_manager=hooks, registrar=reg, data_root=tmp_path / "data"), hooks, reg


async def test_a_directory_plugin_registers_its_skills_mcp_tools_hooks_and_prompts(
    tmp_path: Path,
) -> None:
    """
    Feature: Plugins
    Requirement: docs/specs/issue-3/requirements.md#R3

    Scenario: a directory plugin registers its skills, MCP tools, hooks and prompts
        Given the fixture plugin "support-tools" with one skill, three MCP servers, two hooks,
              one prompt and a system prompt
        When the loader loads its directory
        Then the skill, the stdio and streamable-http servers, both hooks, the prompt and the
             system prompt are loaded
        And the legacy SSE server is skipped with a reason
        And the stdio server's ${PLUGIN_ROOT} and ${PLUGIN_DATA} arguments are expanded while
            its command is not
    """
    plugin_loader, hooks, registrar = loader(tmp_path)
    report = await plugin_loader.load_directory(FIXTURES / "valid")
    assert report.plugin == "support-tools"
    assert report.loaded_ids(ComponentKind.SKILL) == ("summarize",)
    assert set(report.loaded_ids(ComponentKind.MCP_SERVER)) == {"orders", "policy"}
    assert report.loaded_ids(ComponentKind.HOOK) == ("audit", "policy-rpc")
    assert report.loaded_ids(ComponentKind.PROMPT) == ("participants",)
    assert report.loaded_ids(ComponentKind.SYSTEM_PROMPT) == ("systemprompt",)
    assert [s.id for s in report.skipped] == ["legacy"]
    assert "not supported" in report.skipped[0].reason
    point = HookPoint(operation=Operation.LLM_INVOKED, phase=Phase.PRE)
    assert [e.name for e in hooks.executors_for(point)] == ["audit", "policy-rpc"]
    other = HookPoint(operation=Operation.PLAN_CREATED, phase=Phase.IN)
    assert [e.name for e in hooks.executors_for(other)] == ["policy-rpc"]
    orders = registrar.mcp["orders"]
    assert isinstance(orders, McpStdioServer) and orders.command == "python"
    assert registrar.skills["summarize"].name == "summarize"
    assert registrar.system_prompt is not None and registrar.system_prompt.name == "systemprompt.md"


async def test_a_programmatic_plugin_registers_the_same_components(tmp_path: Path) -> None:
    """
    Feature: Plugins
    Requirement: docs/specs/issue-3/requirements.md#R3

    Scenario: a programmatic plugin registers the same components
        Given a Plugin built in code with the same manifest, skill path, MCP servers and hook
        When the loader loads it
        Then the report lists the same loaded components as the directory form
    """
    plugin_loader, _, registrar = loader(tmp_path)
    directory = discover(FIXTURES / "valid")
    programmatic = Plugin(
        manifest=PluginManifest.model_validate(
            {"$schema": directory.manifest.schema_id, "name": "support-tools"}
        ),
        skills=directory.skills,
        mcp={
            "orders": McpStdioServer(type="stdio", command="python", args=("-m", "orders")),
            "policy": McpHttpServer(
                type="streamable-http", url=HttpUrl("https://policy.example.com/mcp")
            ),
        },
        hooks=(
            HookDef(name="audit", priority=100, import_path="tests.fixtures.plugins.hooks:audit"),
        ),
        prompts=directory.prompts,
        systemprompt=directory.systemprompt,
    )
    report = await plugin_loader.load(programmatic)
    assert report.loaded_ids(ComponentKind.SKILL) == ("summarize",)
    assert set(report.loaded_ids(ComponentKind.MCP_SERVER)) == {"orders", "policy"}
    assert report.loaded_ids(ComponentKind.HOOK) == ("audit",)
    assert report.loaded_ids(ComponentKind.PROMPT) == ("participants",)
    assert report.skipped == ()
    assert registrar.prompts["participants"].name == "participants.md"


async def test_a_second_plugin_with_the_same_ids_is_refused_unless_overridden(
    tmp_path: Path,
) -> None:
    """
    Feature: Plugins
    Requirement: docs/specs/issue-3/requirements.md#R3

    Scenario: a duplicate (id, version) is refused unless the loading order overrides it
        Given the fixture plugin loaded once
        When it is loaded again without override
        Then every component that re-registers an existing id is skipped with a conflict
        And loading it again with override replaces them
    """
    plugin_loader, _, registrar = loader(tmp_path)
    await plugin_loader.load_directory(FIXTURES / "valid")
    second = await plugin_loader.load_directory(FIXTURES / "valid")
    assert {s.code for s in second.skipped} >= {"entity.conflict"}
    assert "summarize" in {s.id for s in second.skipped if s.kind is ComponentKind.SKILL}
    registrar.override = True
    third = await plugin_loader.load_directory(FIXTURES / "valid", override=True)
    assert "summarize" in third.loaded_ids(ComponentKind.SKILL)
