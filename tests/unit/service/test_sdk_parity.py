"""SDK parity (issue-25 R6.8, R11): what the CLI gets from its configuration an SDK caller
gets from ``build_runtime`` / ``running_harness`` arguments, and neither ``Settings.load``
nor the runtime ever reads or creates ``~/.tiny-harness``."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiny_harness.config import Settings
from tiny_harness.errors import CommandError, ConfigError
from tiny_harness.harness.commands import (
    BUILTIN_SPECS,
    CommandInvokedIn,
    CommandResult,
    CommandSpec,
)
from tiny_harness.harness.models import FakeLLM
from tiny_harness.harness.plugins import (
    CommandDef,
    ComponentKind,
    HookDef,
    Plugin,
    PluginManifest,
)
from tiny_harness.home import ensure_default_config
from tiny_harness.service import complete_message
from tiny_harness.service.inbox import envelope_of
from tiny_harness.service.runtime import build_runtime

BUILTINS = frozenset(s.name for s in BUILTIN_SPECS)
ENV = {"OPENAI_API_KEY": "sk-unused", "TEMPORAL_API_KEY": "unused"}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty ``HOME``: any read or write of ``~/.tiny-harness`` would show in it."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    return path


def settings(tmp_path: Path) -> Settings:
    return Settings.model_validate(
        {
            "temporal": {"mode": "embedded"},
            "openai": {"api_key": "sk-unused"},
            "server": {"bind": "127.0.0.1:8080", "base_url": "http://127.0.0.1:8080"},
            "store": {"sqlite_path": str(tmp_path / "state" / "tiny-harness.sqlite3")},
        }
    )


def echo(ctx: CommandInvokedIn) -> CommandResult:
    return CommandResult(reply=ctx.arguments)


def test_settings_load_without_a_path_never_reads_or_creates_home(home: Path) -> None:
    """R11.2: with no path, ``Settings.load`` uses only the environment: it neither creates
    ``~/.tiny-harness`` nor reads a default file already there."""
    with pytest.raises(ConfigError):
        Settings.load(None, env=ENV)  # the environment alone is not a whole configuration
    assert list(home.iterdir()) == []
    default = ensure_default_config(home / ".tiny-harness")[0]
    before = default.read_bytes()
    with pytest.raises(ConfigError):
        Settings.load(None, env=ENV)  # a valid default file is still not read
    valid = Settings.load(default, env={"OPENAI_API_KEY": "sk-unused"})
    assert valid.temporal.mode == "embedded"
    assert default.read_bytes() == before


async def test_the_runtime_has_the_built_ins_by_default_and_none_when_asked(
    home: Path, tmp_path: Path
) -> None:
    runtime = await build_runtime(settings(tmp_path), llm=FakeLLM([]))
    assert runtime.commands.names == BUILTINS
    bare = await build_runtime(settings(tmp_path), llm=FakeLLM([]), builtin_commands=False)
    assert bare.commands.names == frozenset()
    assert list(home.iterdir()) == []


async def test_commands_from_code_register_beside_the_built_ins(tmp_path: Path) -> None:
    spec = CommandSpec(name="echo", description="Echo", argument_hint="<text>")
    runtime = await build_runtime(settings(tmp_path), llm=FakeLLM([]), commands=[(spec, echo)])
    assert runtime.commands.specs[-1] == spec
    with pytest.raises(CommandError, match="already registered"):  # R6.5
        await build_runtime(
            settings(tmp_path),
            llm=FakeLLM([]),
            commands=[(CommandSpec(name="status", description="mine"), echo)],
        )


async def test_programmatic_plugins_load_after_the_configured_ones(tmp_path: Path) -> None:
    plugin = Plugin(
        manifest=PluginManifest.model_validate(
            {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "ops"}
        ),
        hooks=(
            HookDef(
                name="status-body",
                import_path="tests.fixtures.plugins.hooks:status",
                points=("command.invoked.in",),
            ),
        ),
        commands=(CommandDef(name="status", description="Plugin status", hook="status-body"),),
    )
    runtime = await build_runtime(settings(tmp_path), llm=FakeLLM([]), plugins=[plugin])
    report = runtime.reports[-1]
    assert report.plugin == "ops" and report.loaded_ids(ComponentKind.COMMAND) == ("status",)
    assert [s.description for s in runtime.commands.specs if s.name == "status"] == [
        "Plugin status"
    ]


def test_complete_message_is_the_control_envelope() -> None:
    """R11.3: task completion is a public function, the message any client sends (R5.1)."""
    msg = complete_message("t-1", participant_id="alice", context_id="ctx-1")
    envelope = envelope_of(msg)
    assert envelope is not None and (envelope.kind, envelope.action) == ("control", "complete")
    assert (msg.task_id, msg.context_id) == ("t-1", "ctx-1")
    assert msg.metadata["participant_id"] == "alice"
    assert msg.message_id
