"""Abuse case 3: plugin paths stay inside the plugin; `command` is never expanded."""

from pathlib import Path

import pytest

from tests.fixtures.plugins.registrar import RecordingRegistrar
from tiny_harness.errors import ComponentSkipped, PluginError
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.plugins import (
    ComponentKind,
    McpStdioServer,
    PluginLoader,
    contained,
    discover,
    prepare_stdio,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "plugins"


def loader(tmp_path: Path) -> PluginLoader:
    return PluginLoader(
        hook_manager=HookManager(), registrar=RecordingRegistrar(), data_root=tmp_path
    )


async def test_plugin_path_escape_rejected(tmp_path: Path) -> None:
    report = await loader(tmp_path).load_directory(FIXTURES / "escape")
    skipped = {s.id: s for s in report.skipped}
    assert set(skipped) == {"outside", "data-escape"}
    assert all("escape" in s.reason or "rooted" in s.reason for s in skipped.values())
    assert report.loaded_ids(ComponentKind.MCP_SERVER) == ("inside",)


async def test_command_with_expansion_rejected(tmp_path: Path) -> None:
    report = await loader(tmp_path).load_directory(FIXTURES / "expansion")
    skipped = {s.id: s for s in report.skipped}
    assert set(skipped) == {"expanded-command"}
    assert skipped["expanded-command"].code == "plugin.invalid"
    assert "command" in skipped["expanded-command"].reason
    assert report.loaded_ids(ComponentKind.MCP_SERVER) == ("fine",)


def test_only_the_two_variables_expand_and_only_in_args_env_cwd(tmp_path: Path) -> None:
    root = FIXTURES / "valid"
    data = tmp_path / "data"
    server = McpStdioServer(
        type="stdio",
        command="python",
        args=("${PLUGIN_ROOT}/x", "${PLUGIN_DATA}/y", "${HOME}/z"),
        env={"A": "${PLUGIN_ROOT}", "B": "${OTHER}"},
        cwd="${PLUGIN_ROOT}",
    )
    params = prepare_stdio(server, root=root, data=data)
    assert params.args == [f"{root.resolve()}/x", f"{data}/y", "${HOME}/z"]
    assert params.env is not None
    assert params.env["A"] == str(root.resolve()) and params.env["B"] == "${OTHER}"
    assert params.env["PLUGIN_ROOT"] == str(root.resolve()) and params.env["PLUGIN_DATA"] == str(
        data
    )
    assert params.cwd == root.resolve()
    with pytest.raises(PluginError):
        prepare_stdio(
            McpStdioServer(type="stdio", command="${PLUGIN_ROOT}/bin"), root=root, data=data
        )


def test_contained_rejects_symlink_and_dotdot_escapes(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    root.mkdir()
    (root / "inside.txt").write_text("x")
    outside = tmp_path / "outside.txt"
    outside.write_text("y")
    (root / "link.txt").symlink_to(outside)
    assert contained(root / "inside.txt", root) == (root / "inside.txt").resolve()
    with pytest.raises(ComponentSkipped):
        contained(root / "link.txt", root)
    with pytest.raises(ComponentSkipped):
        contained(root / ".." / "outside.txt", root)


def test_skill_and_prompt_paths_outside_the_root_are_skipped(tmp_path: Path) -> None:
    plugin = discover(FIXTURES / "valid")
    assert all(p.is_relative_to(plugin.root or Path()) for p in plugin.skills + plugin.prompts)
