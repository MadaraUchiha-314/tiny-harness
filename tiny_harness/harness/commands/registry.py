"""The command registry: specs for the card, bodies on ``command.invoked.in`` (R6.1,
R6.5, R6a.1-6a.7).

``HookDef`` has no matcher, so every command body is wrapped in ``_ForCommand``, which
passes through any context for another command or one already answered. An executor
registered for a command therefore only ever sees that command (abuse case 10), and a
lower-priority body that answers first overrides it (R6a.3). The registry is filled at
build time and frozen before the worker starts; a bad or duplicate name, or a
registration after the freeze, raises ``CommandError``. A registration with
``override`` (an operator plugin replacing a built-in) replaces the spec and retires the
earlier body, so the replacement answers whatever its priority.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import ClassVar

from tiny_harness.errors import CommandError
from tiny_harness.harness.commands.models import CommandInvokedIn, CommandResult, CommandSpec
from tiny_harness.harness.commands.parse import NAME_PATTERN
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.hooks import (
    FunctionExecutor,
    HookContext,
    HookExecutor,
    HookManager,
    HookPoint,
    Operation,
    Phase,
)

COMMAND_IN = HookPoint(operation=Operation.COMMAND_INVOKED, phase=Phase.IN)

CommandHandler = Callable[[CommandInvokedIn], CommandResult | Awaitable[CommandResult]]
"""A programmatic command body: the context in, the result out (sync or async)."""


class Command(Entity):
    """A registered command, as the entity registry and the card see it."""

    kind: ClassVar[EntityKind] = EntityKind.COMMAND

    def __init__(self, spec: CommandSpec) -> None:
        super().__init__(EntityRef(kind=EntityKind.COMMAND, id=spec.name))
        self.spec = spec


class _ForCommand:
    """Runs ``inner`` only for an unanswered ``command.invoked`` context named ``name``."""

    def __init__(self, name: str, inner: HookExecutor) -> None:
        self._command = name
        self._inner = inner
        self.retired = False  # set when an override replaces this body

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def priority(self) -> int:
        return self._inner.priority

    @property
    def points(self) -> frozenset[HookPoint] | None:
        return self._inner.points

    async def handle(self, point: HookPoint, ctx: HookContext) -> HookContext | None:
        if self.retired or not isinstance(ctx, CommandInvokedIn) or ctx.name != self._command:
            return None
        if ctx.result is not None:
            return None
        return await self._inner.handle(point, ctx)


class CommandRegistry:
    """Command specs by name, their bodies registered on ``hooks``."""

    def __init__(self, hooks: HookManager) -> None:
        self._hooks = hooks
        self._specs: dict[str, CommandSpec] = {}
        self._bodies: dict[str, _ForCommand] = {}
        self._frozen = False

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._specs)

    @property
    def specs(self) -> tuple[CommandSpec, ...]:
        """In registration order."""
        return tuple(self._specs.values())

    def register(
        self,
        spec: CommandSpec,
        handler: CommandHandler,
        *,
        priority: int = 500,
        override: bool = False,
    ) -> None:
        """Register ``handler`` as the body of ``/<spec.name>`` (R6.1)."""

        async def body(point: HookPoint, ctx: HookContext) -> HookContext | None:
            assert isinstance(ctx, CommandInvokedIn)
            produced = handler(ctx)
            result = await produced if inspect.isawaitable(produced) else produced
            return ctx.model_copy(update={"result": result})

        executor = FunctionExecutor(
            f"command:{spec.name}", body, priority=priority, points=[COMMAND_IN]
        )
        self.register_executor(spec, executor, override=override)

    def register_executor(
        self, spec: CommandSpec, executor: HookExecutor, *, override: bool = False
    ) -> None:
        """Register any executor (local or remote) as the body of ``/<spec.name>``; it is
        wrapped so it sees only that command. ``override`` replaces a command already
        registered under the name instead of raising."""
        self._check(spec.name, override=override)
        previous = self._bodies.get(spec.name)
        if previous is not None:
            previous.retired = True
        body = _ForCommand(spec.name, executor)
        self._specs[spec.name] = spec  # an override keeps the name's place in the order
        self._bodies[spec.name] = body
        self._hooks.register(body)

    def freeze(self) -> None:
        self._frozen = True

    async def publish(self, registry: Registry) -> None:
        """Add every command to the entity registry as ``EntityKind.COMMAND``."""
        for spec in self._specs.values():
            command = Command(spec)
            await registry.add(RegistryEntry[Command](ref=command.ref, instance=command))

    def _check(self, name: str, *, override: bool = False) -> None:
        if self._frozen:
            raise CommandError("command registry is frozen", name=name)
        if NAME_PATTERN.fullmatch(name) is None:
            raise CommandError("invalid command name; expected [a-z][a-z0-9-]*", name=name)
        if name in self._specs and not override:
            raise CommandError("command already registered", name=name)


__all__ = ["COMMAND_IN", "Command", "CommandHandler", "CommandRegistry"]
