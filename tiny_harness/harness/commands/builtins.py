"""The built-in commands and the built-in role policy (R6.8, R7-R10, abuse cases 1, 2, 4, 5).

Each command is a pure function of ``CommandInvokedIn`` and the runtime's
``ModelCatalog``: it reads the task snapshot and returns intents for the workflow. The
built-in plugin registers them at ``DEFAULT_BODY_PRIORITY`` (R6a.3), so any executor that
answers first, or a plugin command loaded with ``override``, replaces one.

Arguments are opaque text. ``/model`` compares against the catalog's allowlist exactly and
``/effort`` against a closed set; neither echoes a refused value. ``/sub-task`` only
stores its description as a goal. ``/exit`` only asks the sender's client to close; the
task does not change. Nothing here touches a shell, a path or the network.

The role policy is a ``pre`` executor at priority 100: a ``watcher`` may read (``/model``,
``/effort`` without an argument, ``/status``, ``/exit``) but not change, and a sender with
no role on the task may run nothing. An operator tightens it with an executor of their own.
"""

from __future__ import annotations

from typing import Final, get_args

from tiny_harness.config import ReasoningEffort
from tiny_harness.errors import AbortReason, HookAbort
from tiny_harness.harness.commands.models import (
    CommandInvokedIn,
    CommandInvokedPre,
    CommandResult,
    CommandSpec,
    SpawnIntent,
    TaskSettings,
)
from tiny_harness.harness.commands.registry import CommandRegistry
from tiny_harness.harness.core import Role
from tiny_harness.harness.hooks import (
    DEFAULT_BODY_PRIORITY,
    FunctionExecutor,
    HookContext,
    HookManager,
    HookPoint,
    Operation,
    Phase,
)
from tiny_harness.harness.models.catalog import ModelCatalog

EFFORTS: Final[tuple[ReasoningEffort, ...]] = get_args(ReasoningEffort)
ROLE_POLICY_PRIORITY: Final = 100
COMMAND_PRE = HookPoint(operation=Operation.COMMAND_INVOKED, phase=Phase.PRE)

MODEL = CommandSpec(
    name="model", description="Show or choose this task's model", argument_hint="[<model>]"
)
EFFORT = CommandSpec(
    name="effort",
    description="Show or set this task's reasoning effort",
    argument_hint="[low|medium|high]",
)
SUB_TASK = CommandSpec(
    name="sub-task", description="Start a linked sub-task", argument_hint="<description>"
)
STATUS = CommandSpec(name="status", description="Show this task's status")
EXIT = CommandSpec(name="exit", description="Close this client; the task does not change")
BUILTIN_SPECS: Final = (MODEL, EFFORT, SUB_TASK, STATUS, EXIT)

# Commands that change the task when given an argument (/sub-task always does).
_CHANGES_WITH_ARGUMENT: Final = frozenset({MODEL.name, EFFORT.name})


def _model_line(ctx: CommandInvokedIn, catalog: ModelCatalog) -> str:
    chosen = ctx.task.settings.model
    return f"Model: {chosen}" if chosen else f"Model: {catalog.default} (default)"


def _effort_line(ctx: CommandInvokedIn, catalog: ModelCatalog) -> str:
    chosen = ctx.task.settings.reasoning_effort
    if chosen is not None:
        return f"Effort: {chosen}"
    if catalog.default_effort is not None:
        return f"Effort: {catalog.default_effort} (default)"
    return "Effort: provider default"


def model_command(ctx: CommandInvokedIn, catalog: ModelCatalog) -> CommandResult:
    """``/model`` lists; ``/model <name>`` chooses a selectable model (R7.2-7.4)."""
    selectable = ", ".join(catalog.selectable)
    name = ctx.arguments.strip()
    if not name:
        return CommandResult(reply=f"{_model_line(ctx, catalog)}\nSelectable: {selectable}")
    if name not in catalog.selectable:
        return CommandResult(reply=f"refused: not a selectable model. Selectable: {selectable}")
    return CommandResult(reply=f"Model set to {name}.", settings=TaskSettings(model=name))


def effort_command(ctx: CommandInvokedIn, catalog: ModelCatalog) -> CommandResult:
    """``/effort`` reports; ``/effort <value>`` sets one of the accepted efforts (R8.2-8.4)."""
    accepted = ", ".join(EFFORTS)
    value = ctx.arguments.strip()
    if not value:
        return CommandResult(reply=f"{_effort_line(ctx, catalog)}\nAccepted: {accepted}")
    for effort in EFFORTS:
        if value == effort:
            return CommandResult(
                reply=f"Effort set to {effort}.", settings=TaskSettings(reasoning_effort=effort)
            )
    return CommandResult(reply=f"refused: not an accepted effort. Accepted: {accepted}")


def sub_task_command(ctx: CommandInvokedIn) -> CommandResult:
    """``/sub-task <description>`` asks the workflow for a linked conversation sub-task;
    the workflow appends the new id to the reply (R9.1, R9.3)."""
    goal = ctx.arguments.strip()
    if not goal:
        return CommandResult(reply=f"Usage: /{SUB_TASK.name} {SUB_TASK.argument_hint}")
    return CommandResult(reply="Starting a sub-task.", spawn=SpawnIntent(goal=goal))


def status_command(ctx: CommandInvokedIn, catalog: ModelCatalog) -> CommandResult:
    """``/status``: the task from its snapshot, without a model call (R10.1)."""
    task = ctx.task
    state = f"{task.state} · {task.sub_state.value}" if task.sub_state else task.state
    plan = f"{task.steps_done}/{task.steps_total} steps done" if task.steps_total else "none"
    lines = [
        f"Task {task.id} · {task.name}",
        f"State: {state}",
        _model_line(ctx, catalog),
        _effort_line(ctx, catalog),
        f"Plan: {plan}",
    ]
    if task.children:
        lines.append("Sub-tasks:")
        lines.extend(f"- {child.task_id} · {child.state}" for child in task.children)
    else:
        lines.append("Sub-tasks: none")
    return CommandResult(reply="\n".join(lines))


def exit_command(ctx: CommandInvokedIn) -> CommandResult:
    """``/exit``: ask the sender's client to close (issue-32). The task does not change;
    a client that cannot close shows the reply."""
    return CommandResult(reply="Closing this client.", close_client=True)


def register_builtin_commands(commands: CommandRegistry, catalog: ModelCatalog) -> None:
    """Register the built-ins at ``DEFAULT_BODY_PRIORITY`` (R6.8, R6a.3)."""
    commands.register(
        MODEL, lambda ctx: model_command(ctx, catalog), priority=DEFAULT_BODY_PRIORITY
    )
    commands.register(
        EFFORT, lambda ctx: effort_command(ctx, catalog), priority=DEFAULT_BODY_PRIORITY
    )
    commands.register(SUB_TASK, sub_task_command, priority=DEFAULT_BODY_PRIORITY)
    commands.register(
        STATUS, lambda ctx: status_command(ctx, catalog), priority=DEFAULT_BODY_PRIORITY
    )
    commands.register(EXIT, exit_command, priority=DEFAULT_BODY_PRIORITY)


async def _role_policy(point: HookPoint, ctx: HookContext) -> HookContext | None:
    if not isinstance(ctx, CommandInvokedPre):
        return None
    if ctx.sender_role is None:
        raise HookAbort("the sender has no role on this task", reason=AbortReason.REFUSED)
    changes = ctx.name == SUB_TASK.name or (
        ctx.name in _CHANGES_WITH_ARGUMENT and ctx.arguments.strip() != ""
    )
    if changes and ctx.sender_role is Role.WATCHER:
        raise HookAbort(
            f"a watcher may not change the task with /{ctx.name}", reason=AbortReason.REFUSED
        )
    return None


def register_role_policy(hooks: HookManager) -> None:
    """The built-in ``command.invoked.pre`` role check (abuse case 4)."""
    hooks.register(
        FunctionExecutor(
            "command.role-policy", _role_policy, priority=ROLE_POLICY_PRIORITY, points=[COMMAND_PRE]
        )
    )


__all__ = [
    "BUILTIN_SPECS",
    "EFFORT",
    "EFFORTS",
    "EXIT",
    "MODEL",
    "ROLE_POLICY_PRIORITY",
    "STATUS",
    "SUB_TASK",
    "effort_command",
    "exit_command",
    "model_command",
    "register_builtin_commands",
    "register_role_policy",
    "status_command",
    "sub_task_command",
]
