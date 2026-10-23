"""T1 (issue-38 R1.2): a surface command runs in the client. ``CommandSpec.runs_on`` says
where a command runs; ``/attach`` is the built-in surface command, listed on the card
(as ``runsOn``) only where the agent takes media, and the server's own body answers a
client that does not implement it."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tiny_harness.config import Settings
from tiny_harness.harness.commands import (
    ATTACH,
    BUILTIN_SPECS,
    SURFACE_SPECS,
    CommandInvokedIn,
    CommandRegistry,
    CommandsExtensionParams,
    CommandSpec,
    TaskSnapshot,
    attach_command,
    register_builtin_commands,
)
from tiny_harness.harness.core import Role
from tiny_harness.harness.hooks import HookManager, HookPoint, Operation, Phase
from tiny_harness.harness.models import FakeLLM, ModelCatalog
from tiny_harness.service.runtime import build_runtime

CATALOG = ModelCatalog(default="model-a", selectable=("model-a",))
IN = HookPoint(operation=Operation.COMMAND_INVOKED, phase=Phase.IN)
REPLY = "/attach runs in your client; this client cannot attach files"


def invoked(name: str, arguments: str = "") -> CommandInvokedIn:
    return CommandInvokedIn(
        task_id="t-1",
        correlation_id="c-1",
        name=name,
        arguments=arguments,
        sender="alice",
        sender_role=Role.REPORTER,
        task=TaskSnapshot(id="t-1", name="Room", state="INPUT_REQUIRED"),
    )


def test_a_command_runs_on_the_agent_by_default() -> None:
    spec = CommandSpec(name="echo", description="Echo")
    assert spec.runs_on == "agent"
    assert all(s.runs_on == "agent" for s in BUILTIN_SPECS)
    with pytest.raises(ValidationError):
        CommandSpec.model_validate({"name": "x", "description": "x", "runs_on": "browser"})


def test_attach_is_a_surface_command_with_a_path_argument() -> None:
    assert ATTACH.name == "attach" and ATTACH.runs_on == "surface"
    assert ATTACH.argument_hint == "<path>"
    assert SURFACE_SPECS == (ATTACH,)


def test_the_card_names_runs_on_only_for_a_surface_command() -> None:
    """``runsOn`` is optional in commands extension v1: an agent command's entry is the
    0.8.0 entry, a surface command's adds ``"runsOn": "surface"``."""
    params = CommandsExtensionParams(commands=(*BUILTIN_SPECS, ATTACH))
    dumped = params.model_dump(mode="json")
    entries = dumped["commands"]
    assert entries[0] == {
        "name": "model",
        "description": "Show or choose this task's model",
        "argument_hint": "[<model>]",
    }
    assert entries[-1] == {
        "name": "attach",
        "description": ATTACH.description,
        "argument_hint": "<path>",
        "runsOn": "surface",
    }
    assert CommandsExtensionParams.model_validate(dumped) == params
    parsed = CommandSpec.model_validate({"name": "attach", "description": "d", "runsOn": "surface"})
    assert parsed.runs_on == "surface"


def test_attach_answers_a_client_that_cannot_attach() -> None:
    result = attach_command(invoked("attach", "~/photo.png"))
    assert result.reply == REPLY
    assert result.settings is None and result.spawn is None


async def test_attach_registers_only_where_the_agent_takes_media() -> None:
    plain = CommandRegistry(HookManager())
    register_builtin_commands(plain, CATALOG)
    assert plain.specs == BUILTIN_SPECS

    hooks = HookManager()
    media = CommandRegistry(hooks)
    register_builtin_commands(media, CATALOG, attach=True)
    assert media.specs == (*BUILTIN_SPECS, ATTACH)
    out = await hooks.run(IN, invoked("attach", "photo.png"))
    assert out.result is not None and out.result.reply == REPLY


async def test_the_runtime_lists_attach_only_with_media(tmp_path: Path) -> None:
    """The card of an agent without ``[media]`` stays the 0.8.0 card (T10)."""
    base = {
        "temporal": {"mode": "embedded"},
        "openai": {"api_key": "sk-unused"},
        "server": {"bind": "127.0.0.1:8080", "base_url": "http://127.0.0.1:8080"},
        "store": {"sqlite_path": str(tmp_path / "state" / "tiny-harness.sqlite3")},
    }
    plain = await build_runtime(Settings.model_validate(base), llm=FakeLLM([]))
    assert "attach" not in plain.commands.names
    media = await build_runtime(
        Settings.model_validate({**base, "media": {"dir": str(tmp_path / "media")}}),
        llm=FakeLLM([]),
    )
    assert media.commands.specs[-1] == ATTACH
