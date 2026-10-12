"""Command primitives (R6.1, R6.5, R6a.1-6a.5, R6a.7, abuse case 10): the hook operation,
the registry and the per-name body filter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tiny_harness.errors import CommandError
from tiny_harness.harness.commands import (
    Command,
    CommandInvokedIn,
    CommandInvokedPost,
    CommandRegistry,
    CommandResult,
    CommandSpec,
    SpawnIntent,
    TaskSettings,
    TaskSnapshot,
)
from tiny_harness.harness.core import Role
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry
from tiny_harness.harness.hooks import (
    FunctionExecutor,
    HookContext,
    HookManager,
    HookPoint,
    Operation,
    Phase,
)

IN = HookPoint(operation=Operation.COMMAND_INVOKED, phase=Phase.IN)


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


def echo(ctx: CommandInvokedIn) -> CommandResult:
    return CommandResult(reply=f"{ctx.name}:{ctx.arguments}")


def test_the_operation_joins_the_catalogue() -> None:
    assert Operation.COMMAND_INVOKED.value == "command.invoked"
    assert EntityKind.COMMAND.value == "command"
    assert issubclass(CommandInvokedPost, CommandInvokedIn)


def test_models_are_closed() -> None:
    with pytest.raises(ValidationError):
        TaskSettings.model_validate({"reasoning_effort": "extreme"})
    with pytest.raises(ValidationError):
        CommandResult.model_validate({"reply": "x", "extra": 1})
    result = CommandResult(
        reply="ok",
        settings=TaskSettings(model="m"),
        spawn=SpawnIntent(goal="write notes"),
    )
    assert result.settings is not None and result.settings.reasoning_effort is None
    assert TaskSnapshot(id="t", name="n", state="WORKING").children == ()


async def test_a_registered_handler_answers_only_its_own_name() -> None:
    hooks = HookManager()
    commands = CommandRegistry(hooks)
    commands.register(CommandSpec(name="echo", description="Echo"), echo)
    commands.register(CommandSpec(name="other", description="Other"), echo)
    out = await hooks.run(IN, invoked("echo", "hi"))
    assert out.result == CommandResult(reply="echo:hi")
    other = await hooks.run(IN, invoked("other"))
    assert other.result == CommandResult(reply="other:")
    nobody = await hooks.run(IN, invoked("missing"))
    assert nobody.result is None
    assert commands.names == frozenset({"echo", "other"})
    assert [s.name for s in commands.specs] == ["echo", "other"]


async def test_an_async_handler_is_awaited() -> None:
    async def later(ctx: CommandInvokedIn) -> CommandResult:
        return CommandResult(reply="later")

    hooks = HookManager()
    CommandRegistry(hooks).register(CommandSpec(name="later", description="d"), later)
    assert (await hooks.run(IN, invoked("later"))).result == CommandResult(reply="later")


async def test_a_lower_priority_body_overrides_and_the_default_then_passes_through() -> None:
    hooks = HookManager()
    commands = CommandRegistry(hooks)
    commands.register(CommandSpec(name="status", description="d"), echo, priority=1000)

    async def override(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, CommandInvokedIn)
        if ctx.name != "status":
            return None
        return ctx.model_copy(update={"result": CommandResult(reply="overridden")})

    hooks.register(FunctionExecutor("tighter", override, priority=100, points=[IN]))
    assert (await hooks.run(IN, invoked("status"))).result == CommandResult(reply="overridden")


async def test_a_wrapped_executor_sees_only_its_own_unanswered_command() -> None:
    """Abuse case 10: a command's body (``_ForCommand``) only ever receives the command it
    implements, and never one another body has already answered."""
    seen: list[str] = []

    async def inner_handler(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, CommandInvokedIn)
        seen.append(ctx.name)
        return ctx.model_copy(update={"result": CommandResult(reply="inner")})

    hooks = HookManager()
    commands = CommandRegistry(hooks)
    inner = FunctionExecutor("remote", inner_handler, priority=700, points=[IN])
    commands.register_executor(CommandSpec(name="deploy", description="d"), inner)
    (wrapped,) = hooks.executors_for(IN)
    assert wrapped.priority == 700 and wrapped.points == frozenset({IN})
    assert (await hooks.run(IN, invoked("status"))).result is None
    done = invoked("deploy").model_copy(update={"result": CommandResult(reply="first")})
    assert (await hooks.run(IN, done)).result == CommandResult(reply="first")
    out = await hooks.run(IN, invoked("deploy"))
    assert out.result == CommandResult(reply="inner")
    assert seen == ["deploy"]


@pytest.mark.parametrize("name", ["", "Model", "9x", "-x", "a b", "a_b", "a/b"])
def test_an_invalid_name_raises(name: str) -> None:
    commands = CommandRegistry(HookManager())
    with pytest.raises(CommandError):
        commands.register(CommandSpec(name=name, description="d"), echo)


def test_a_duplicate_name_raises_and_leaves_the_first() -> None:
    hooks = HookManager()
    commands = CommandRegistry(hooks)
    commands.register(CommandSpec(name="echo", description="first"), echo)
    with pytest.raises(CommandError, match="already registered"):
        commands.register(CommandSpec(name="echo", description="second"), echo)
    assert [s.description for s in commands.specs] == ["first"]
    assert len(hooks.executors_for(IN)) == 1


def test_a_frozen_registry_refuses_registration() -> None:
    commands = CommandRegistry(HookManager())
    commands.freeze()
    with pytest.raises(CommandError, match="frozen"):
        commands.register(CommandSpec(name="late", description="d"), echo)


async def test_publish_adds_each_command_to_the_entity_registry() -> None:
    commands = CommandRegistry(HookManager())
    spec = CommandSpec(name="echo", description="Echo", argument_hint="<text>")
    commands.register(spec, echo)
    registry = Registry()
    await commands.publish(registry)
    ref = EntityRef(kind=EntityKind.COMMAND, id="echo")
    assert list(registry.list(EntityKind.COMMAND)) == [ref]
    assert (await registry.get(ref, Command)).spec == spec


async def test_an_override_replaces_the_spec_and_retires_the_previous_body() -> None:
    """A plugin loaded with ``override`` replaces an earlier command of the same name,
    whatever the two bodies' priorities: the earlier body never answers again."""
    hooks = HookManager()
    commands = CommandRegistry(hooks)
    commands.register(CommandSpec(name="status", description="built-in"), echo, priority=100)
    commands.register(
        CommandSpec(name="status", description="plugin"),
        lambda ctx: CommandResult(reply="plugin"),
        priority=2000,
        override=True,
    )
    assert [s.description for s in commands.specs] == ["plugin"]
    assert (await hooks.run(IN, invoked("status"))).result == CommandResult(reply="plugin")
