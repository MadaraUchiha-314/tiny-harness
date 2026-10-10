"""Hook points, the typed context base, executors and the manager (R2.1-R2.5, R2.10).

Every lifecycle operation has a ``pre``, ``in`` and ``post`` hook point. A hook executor
is a chain element: it receives the typed context the previous executor returned and
returns a replacement or ``None`` to pass through (sherma's ``HookManager`` semantics).
``pre`` replaces the operation's input, ``post`` its output, and ``in`` its body: the
built-in plugin registers each default body at priority ``DEFAULT_BODY_PRIORITY``, so
any executor with a lower priority that sets the context's ``result`` wins.

Hooks never run in workflow code: the activity wrapper runs the chain around each
operation's body (R2.11).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

DEFAULT_BODY_PRIORITY = 1000
"""Priority of the built-in plugin's default ``in`` bodies; lower runs first and wins."""


class Operation(StrEnum):
    """Every lifecycle operation the harness performs (R2.1)."""

    REQUEST_RECEIVED = "request.received"
    TASK_CREATED = "task.created"
    TASK_STATE_CHANGED = "task.state_changed"
    TASK_COMPLETE = "task.complete"
    CONTEXT_CREATED = "context.created"
    LLM_INVOKED = "llm.invoked"
    TOOL_CALLS_EXTRACTED = "tool_calls.extracted"
    TOOL_INVOKED = "tool.invoked"
    SYSTEM_ONE_INVOKED = "system_one.invoked"
    PLAN_CREATED = "plan.created"
    STEP_STARTED = "step.started"
    STEP_FINISHED = "step.finished"
    SUBTASK_SPAWNED = "subtask.spawned"
    HELP_REQUESTED = "help.requested"
    HELP_DECIDED = "help.decided"
    CHANNEL_SENT = "channel.sent"
    CHANNEL_RECEIVED = "channel.received"
    COMPACTION_TRIGGER = "compaction.trigger"
    COMPACTION_KEEP = "compaction.keep"
    COMPACTION_SUMMARISE = "compaction.summarise"
    PERSISTENCE_READ = "persistence.read"
    PERSISTENCE_WRITE = "persistence.write"
    ACTIVITY_FAILED = "activity.failed"
    ACTIVITY_RETRIED = "activity.retried"
    HEARTBEAT_TICK = "heartbeat.tick"
    SHUTDOWN = "shutdown"
    SKILL_LOADED = "skill.loaded"
    SKILL_UNLOADED = "skill.unloaded"
    AGENT_INVOKED = "agent.invoked"


class Phase(StrEnum):
    """When, relative to the operation's body, an executor runs."""

    PRE = "pre"
    IN = "in"
    POST = "post"


class HookPoint(BaseModel, frozen=True):
    """One ``(operation, phase)`` pair."""

    operation: Operation
    phase: Phase

    def __str__(self) -> str:
        return f"{self.operation.value}.{self.phase.value}"


def all_hook_points() -> tuple[HookPoint, ...]:
    """Every point of the catalogue, in operation order (R2.1)."""
    return tuple(HookPoint(operation=op, phase=ph) for op in Operation for ph in Phase)


class HookContext(BaseModel):
    """Base of every typed context: serialisable, carries references, not live objects
    (R2.10). Subclasses add the operation's input, output or replaceable ``result``."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    correlation_id: str
    attempt: int = 1


@runtime_checkable
class HookExecutor(Protocol):
    """A chain element. ``points`` lists the hook points it handles (``None`` = all)."""

    @property
    def name(self) -> str: ...

    @property
    def priority(self) -> int: ...

    @property
    def points(self) -> frozenset[HookPoint] | None: ...

    async def handle(self, point: HookPoint, ctx: HookContext) -> HookContext | None: ...


Handler = Callable[[HookPoint, HookContext], Awaitable[HookContext | None]]


class FunctionExecutor:
    """A ``HookExecutor`` around one async function; what plugins and tests mostly need."""

    def __init__(
        self,
        name: str,
        handler: Handler,
        *,
        priority: int = 500,
        points: Iterable[HookPoint] | None = None,
    ) -> None:
        self._name = name
        self._handler = handler
        self._priority = priority
        self._points = None if points is None else frozenset(points)

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def points(self) -> frozenset[HookPoint] | None:
        return self._points

    async def handle(self, point: HookPoint, ctx: HookContext) -> HookContext | None:
        return await self._handler(point, ctx)


class HookManager:
    """Runs the executor chain for a hook point in ``(priority, registration order)``."""

    def __init__(self) -> None:
        self._executors: list[tuple[int, int, HookExecutor]] = []
        self._counter = 0

    def register(self, executor: HookExecutor) -> None:
        self._executors.append((executor.priority, self._counter, executor))
        self._counter += 1
        self._executors.sort(key=lambda item: (item[0], item[1]))

    def executors_for(self, point: HookPoint) -> list[HookExecutor]:
        return [
            executor
            for _, _, executor in self._executors
            if executor.points is None or point in executor.points
        ]

    async def run[C: HookContext](self, point: HookPoint, ctx: C) -> C:
        """Pass ``ctx`` through every executor registered for ``point``. A returned context
        replaces the input for the next executor; ``None`` passes it through unchanged; a
        context of another type is a programming error. ``HookAbort`` propagates (R2.4)."""
        current = ctx
        for executor in self.executors_for(point):
            replacement = await executor.handle(point, current)
            if replacement is None:
                continue
            if not isinstance(replacement, type(ctx)):
                raise TypeError(
                    f"hook executor {executor.name!r} returned {type(replacement).__name__} "
                    f"for {point}, expected {type(ctx).__name__}"
                )
            current = replacement
        return current


__all__ = [
    "DEFAULT_BODY_PRIORITY",
    "FunctionExecutor",
    "Handler",
    "HookContext",
    "HookExecutor",
    "HookManager",
    "HookPoint",
    "Operation",
    "Phase",
    "all_hook_points",
]
