"""A plugin's ``commands.json`` (issue-25 R6a.6-6a.8, abuse case 10): commands are resolved
before the hook loop, each body is a command-owned ``HookDef`` registered only through
``_ForCommand``, and every invalid entry is skipped with its reason."""

from __future__ import annotations

import json
from pathlib import Path

from tests.fixtures.plugins.registrar import RecordingRegistrar
from tiny_harness.harness.commands import (
    CommandInvokedIn,
    CommandRegistry,
    CommandResult,
    CommandSpec,
    TaskSnapshot,
)
from tiny_harness.harness.core import Role
from tiny_harness.harness.hooks import HookManager, HookPoint, Operation, Phase
from tiny_harness.harness.plugins import (
    NAMESPACE,
    CommandDef,
    ComponentKind,
    HookDef,
    Plugin,
    PluginLoader,
    PluginManifest,
    discover,
)

IN = HookPoint(operation=Operation.COMMAND_INVOKED, phase=Phase.IN)
DEPLOY = "tests.fixtures.plugins.hooks:deploy"
MANIFEST = PluginManifest.model_validate(
    {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "ops"}
)


def invoked(name: str, arguments: str = "") -> CommandInvokedIn:
    return CommandInvokedIn(
        task_id="t-1",
        correlation_id="c-1",
        name=name,
        arguments=arguments,
        sender="alice",
        sender_role=Role.REPORTER,
        task=TaskSnapshot(id="t-1", name="Audit", state="INPUT_REQUIRED"),
    )


def body_hook(name: str = "deploy-body", points: tuple[str, ...] | None = None) -> HookDef:
    return HookDef(
        name=name, import_path=DEPLOY, points=("command.invoked.in",) if points is None else points
    )


def command(name: str = "deploy", hook: str = "deploy-body") -> CommandDef:
    return CommandDef(name=name, description="Deploy", argument_hint="<env>", hook=hook)


def setup(tmp_path: Path) -> tuple[PluginLoader, HookManager, CommandRegistry]:
    hooks = HookManager()
    commands = CommandRegistry(hooks)
    loader = PluginLoader(
        hook_manager=hooks, registrar=RecordingRegistrar(), data_root=tmp_path, commands=commands
    )
    return loader, hooks, commands


def plugin(hooks: tuple[HookDef, ...], commands: tuple[CommandDef, ...]) -> Plugin:
    return Plugin(manifest=MANIFEST, hooks=hooks, commands=commands)


async def test_a_declared_command_is_registered_and_answers_only_its_own_name(
    tmp_path: Path,
) -> None:
    loader, hooks, commands = setup(tmp_path)
    report = await loader.load(plugin((body_hook(),), (command(),)))
    assert report.loaded_ids(ComponentKind.COMMAND) == ("deploy",)
    assert report.loaded_ids(ComponentKind.HOOK) == ()  # command-owned: not an ordinary hook
    assert report.skipped == ()
    assert commands.specs == (
        CommandSpec(name="deploy", description="Deploy", argument_hint="<env>"),
    )
    assert (await hooks.run(IN, invoked("deploy", "prod"))).result == CommandResult(
        reply="deployed prod"
    )
    # the fixture body answers anything it is handed; _ForCommand never hands it another
    assert (await hooks.run(IN, invoked("status"))).result is None


async def test_discover_reads_commands_json_from_the_namespace_directory(tmp_path: Path) -> None:
    root = tmp_path / "ops"
    (root / NAMESPACE).mkdir(parents=True)
    (root / "plugin.json").write_text(MANIFEST.model_dump_json(by_alias=True, exclude_none=True))
    hooks_json = {"hooks": [body_hook().model_dump(mode="json", exclude_none=True)]}
    (root / NAMESPACE / "hooks.json").write_text(json.dumps(hooks_json))
    commands_json = {"commands": [command().model_dump(mode="json")]}
    (root / NAMESPACE / "commands.json").write_text(json.dumps(commands_json))
    found = discover(root)
    assert found.commands == (command(),)
    loader, _, commands = setup(tmp_path / "data")
    report = await loader.load(found)
    assert report.loaded_ids(ComponentKind.COMMAND) == ("deploy",)
    assert commands.names == frozenset({"deploy"})


async def test_an_invalid_commands_json_is_noted_and_the_rest_loads(tmp_path: Path) -> None:
    root = tmp_path / "ops"
    (root / NAMESPACE).mkdir(parents=True)
    (root / "plugin.json").write_text(MANIFEST.model_dump_json(by_alias=True, exclude_none=True))
    (root / NAMESPACE / "commands.json").write_text('{"commands": [{"name": "x"}]}')
    found = discover(root)
    assert found.commands == () and any("commands.json ignored" in n for n in found.notes)


async def test_each_invalid_command_is_skipped_with_its_reason(tmp_path: Path) -> None:
    loader, hooks, commands = setup(tmp_path)
    report = await loader.load(
        plugin(
            (
                body_hook("bad-name-body"),
                body_hook("extra-points", ("command.invoked.in", "llm.invoked.pre")),
                body_hook("wrong-point", ("command.invoked.pre",)),
                HookDef(name="all-points", import_path=DEPLOY),  # points: every point
                body_hook("shared"),
            ),
            (
                command("Deploy", "bad-name-body"),  # invalid name
                command("ghost", "nowhere"),  # unknown hook
                command("wide", "extra-points"),  # extra points
                command("early", "wrong-point"),  # not the in point
                command("any", "all-points"),  # unrestricted points
                command("shared-a", "shared"),
                command("shared-b", "shared"),  # a hook already owned by a command
                command("shared-a", "shared"),  # duplicate name
            ),
        )
    )
    reasons = {s.id: s.reason for s in report.skipped if s.kind is ComponentKind.COMMAND}
    assert set(reasons) == {"Deploy", "ghost", "wide", "early", "any", "shared-b", "shared-a"}
    assert "name" in reasons["Deploy"]
    assert "no hook" in reasons["ghost"]
    assert all("command.invoked.in" in reasons[n] for n in ("wide", "early", "any"))
    assert "owned" in reasons["shared-b"]
    assert "already" in reasons["shared-a"]
    assert report.loaded_ids(ComponentKind.COMMAND) == ("shared-a",)
    assert commands.names == frozenset({"shared-a"})
    # no command-owned hook ever lands on the manager unfiltered: the only executor is the
    # one wrapped body, which ignores every other command
    (only,) = hooks.executors_for(IN)
    assert (await hooks.run(IN, invoked("wide"))).result is None
    assert (await hooks.run(IN, invoked("shared-a", "x"))).result == CommandResult(
        reply="deployed x"
    )
    assert only.points == frozenset({IN})
    llm_pre = HookPoint(operation=Operation.LLM_INVOKED, phase=Phase.PRE)
    assert hooks.executors_for(llm_pre) == []


async def test_ordinary_hooks_still_load_beside_command_owned_ones(tmp_path: Path) -> None:
    loader, hooks, _ = setup(tmp_path)
    audit = HookDef(name="audit", import_path="tests.fixtures.plugins.hooks:audit")
    report = await loader.load(plugin((audit, body_hook()), (command(),)))
    assert report.loaded_ids(ComponentKind.HOOK) == ("audit",)
    assert report.loaded_ids(ComponentKind.COMMAND) == ("deploy",)
    assert len(hooks.executors_for(IN)) == 2


async def test_a_name_already_registered_is_skipped_unless_the_load_overrides(
    tmp_path: Path,
) -> None:
    loader, hooks, commands = setup(tmp_path)
    commands.register(
        CommandSpec(name="deploy", description="built-in"),
        lambda ctx: CommandResult(reply="built-in"),
        priority=1000,
    )
    report = await loader.load(plugin((body_hook(),), (command(),)))
    (skipped,) = report.skipped
    assert skipped.kind is ComponentKind.COMMAND and "already" in skipped.reason
    assert (await hooks.run(IN, invoked("deploy"))).result == CommandResult(reply="built-in")

    report = await loader.load(plugin((body_hook(),), (command(),)), override=True)
    assert report.loaded_ids(ComponentKind.COMMAND) == ("deploy",)
    assert [s.description for s in commands.specs] == ["Deploy"]
    assert (await hooks.run(IN, invoked("deploy", "prod"))).result == CommandResult(
        reply="deployed prod"
    )


async def test_without_a_command_registry_declared_commands_are_skipped(tmp_path: Path) -> None:
    hooks = HookManager()
    loader = PluginLoader(hook_manager=hooks, registrar=RecordingRegistrar(), data_root=tmp_path)
    report = await loader.load(plugin((body_hook(),), (command(),)))
    assert [s.id for s in report.skipped] == ["deploy"]
    assert hooks.executors_for(IN) == []


async def test_an_invalid_commands_json_leaves_no_command_hook_unfiltered(tmp_path: Path) -> None:
    """
    Feature: Plugin commands (critic C1, fail closed)
    Scenario: a commands.json that does not validate takes its command hooks with it
        Given a plugin whose hooks.json declares "deploy-body" on command.invoked.in
        And whose commands.json is invalid (an entry with no description)
        When the plugin is discovered and loaded
        Then "deploy-body" is not registered as an ordinary hook
        And /status reaches no plugin body, while a hook on another point still loads
    """
    root = tmp_path / "ops"
    (root / NAMESPACE).mkdir(parents=True)
    (root / "plugin.json").write_text(MANIFEST.model_dump_json(by_alias=True, exclude_none=True))
    other = HookDef(name="audit", import_path=DEPLOY, points=("task.complete.post",))
    hooks_json = {
        "hooks": [h.model_dump(mode="json", exclude_none=True) for h in (body_hook(), other)]
    }
    (root / NAMESPACE / "hooks.json").write_text(json.dumps(hooks_json))
    (root / NAMESPACE / "commands.json").write_text(
        '{"commands": [{"name": "deploy", "hook": "deploy-body"}]}'
    )
    found = discover(root)
    assert [h.name for h in found.hooks] == ["audit"]
    loader, hooks, _ = setup(tmp_path / "data")
    report = await loader.load(found)
    assert report.loaded_ids(ComponentKind.HOOK) == ("audit",)
    assert (await hooks.run(IN, invoked("status"))).result is None
