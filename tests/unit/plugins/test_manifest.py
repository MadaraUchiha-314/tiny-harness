"""Manifest validation (R3.1, R3.5): schema violations are fatal, unknown top-level keys are not."""

from pathlib import Path

import pytest
from pydantic import HttpUrl

from tiny_harness.errors import PluginError
from tiny_harness.harness.plugins import HookDef, discover, parse_manifest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "plugins"


def test_malformed_manifest_is_fatal_and_names_the_path() -> None:
    with pytest.raises(PluginError) as info:
        discover(FIXTURES / "malformed")
    assert info.value.manifest_path.endswith("malformed/plugin.json")
    assert info.value.code == "plugin.invalid"


def test_missing_manifest_is_fatal(tmp_path: Path) -> None:
    with pytest.raises(PluginError):
        discover(tmp_path)


def test_unknown_top_level_fields_and_non_object_extensions_are_reported_not_fatal() -> None:
    manifest, notes = parse_manifest(FIXTURES / "unknown-keys" / "plugin.json")
    assert manifest.name == "tolerant"
    assert any("unknownTopLevel" in n for n in notes) and any("extensions" in n for n in notes)


def test_invalid_mcp_json_disables_mcp_but_loads_the_rest(tmp_path: Path) -> None:
    (tmp_path / "plugin.json").write_text(
        '{"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "p"}'
    )
    (tmp_path / "mcp.json").write_text('{"mcpServers": {}}')
    plugin = discover(tmp_path)
    assert plugin.mcp == {} and any("MCP disabled" in n for n in plugin.notes)


def test_hook_def_needs_exactly_one_transport() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        HookDef(name="h")
    with pytest.raises(ValueError, match="exactly one"):
        HookDef(name="h", import_path="a:b", url=HttpUrl("https://x.example/rpc"))


def test_skills_are_only_immediate_children_with_skill_md(tmp_path: Path) -> None:
    (tmp_path / "plugin.json").write_text(
        '{"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "p"}'
    )
    (tmp_path / "skills" / "deep" / "nested").mkdir(parents=True)
    (tmp_path / "skills" / "deep" / "nested" / "SKILL.md").write_text("---\nname: nested\n---\n")
    (tmp_path / "skills" / "flat").mkdir()
    (tmp_path / "skills" / "flat" / "SKILL.md").write_text("---\nname: flat\n---\n")
    assert [p.name for p in discover(tmp_path).skills] == ["flat"]
