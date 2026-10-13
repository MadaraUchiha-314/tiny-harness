"""What a command is, what it may return, and the ``command.invoked`` contexts (R6, R6a).

A command's handler is a pure function of ``CommandInvokedIn``: it reads the snapshot of
the task and returns a ``CommandResult``. It never touches the task itself; the workflow
applies ``settings`` and ``spawn`` deterministically and emits the ``reply``.
``close_client`` asks the sender's client to close; the workflow only marks the reply.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel, ConfigDict

from tiny_harness.config import ReasoningEffort
from tiny_harness.harness.core import HarnessTask, Role, StepState, SubState
from tiny_harness.harness.hooks import HookContext


class CommandSpec(BaseModel, frozen=True):
    """What clients see on the card (R6.7). ``name`` must match ``[a-z][a-z0-9-]*``; the
    registry enforces it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    argument_hint: str = ""


COMMANDS_EXT_URI: Final = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/commands/v1"


class CommandsExtensionParams(BaseModel, frozen=True):
    """The commands extension's card ``params``: every registered command, in registration
    order, for clients to offer as ``/`` completions (R6.7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    commands: tuple[CommandSpec, ...] = ()


def commands_extension_schema() -> dict[str, object]:
    """The published JSON Schema (``docs/a2a/ext/commands.json``)."""
    schema = CommandsExtensionParams.model_json_schema()
    schema["$id"] = f"{COMMANDS_EXT_URI}/schema.json"
    return schema


class CommandCall(BaseModel, frozen=True):
    """A parsed ``/<name> <arguments>``; ``arguments`` is the raw remainder."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    arguments: str = ""


class TaskSettings(BaseModel, frozen=True):
    """A task's model settings; ``None`` means "the configured default" (R7, R8)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str | None = None
    reasoning_effort: ReasoningEffort | None = None


class SpawnIntent(BaseModel, frozen=True):
    """Ask the workflow to create a conversation sub-task (R9.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal: str


class CommandResult(BaseModel, frozen=True):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reply: str
    settings: TaskSettings | None = None  # applied by the workflow
    spawn: SpawnIntent | None = None  # spawned by the workflow
    close_client: bool = False  # the reply asks the sender's client to close (issue-32)


class ChildSnapshot(BaseModel, frozen=True):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    state: str


class TaskSnapshot(BaseModel, frozen=True):
    """What a handler may know about the task: references and names, no live objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    state: str
    sub_state: SubState | None = None
    settings: TaskSettings = TaskSettings()
    steps_done: int = 0
    steps_total: int = 0
    children: tuple[ChildSnapshot, ...] = ()

    @classmethod
    def of(cls, task: HarnessTask, children: Sequence[ChildSnapshot] = ()) -> TaskSnapshot:
        ext = task.ext
        steps = ext.plan.steps if ext.plan is not None else ()
        return cls(
            id=task.id,
            name=ext.name,
            state=task.state_name,
            sub_state=task.sub_state,
            settings=TaskSettings(model=ext.model, reasoning_effort=ext.reasoning_effort),
            steps_done=sum(1 for s in steps if s.state is StepState.DONE),
            steps_total=len(steps),
            children=tuple(children),
        )


class CommandInvokedPre(HookContext):
    name: str
    arguments: str
    sender: str
    sender_role: Role | None  # None: the sender holds no role; the built-in pre refuses it
    task: TaskSnapshot


class CommandInvokedIn(CommandInvokedPre):
    result: CommandResult | None = None


class CommandInvokedPost(CommandInvokedIn): ...


__all__ = [
    "COMMANDS_EXT_URI",
    "ChildSnapshot",
    "CommandCall",
    "CommandInvokedIn",
    "CommandInvokedPost",
    "CommandInvokedPre",
    "CommandResult",
    "CommandSpec",
    "CommandsExtensionParams",
    "SpawnIntent",
    "TaskSettings",
    "TaskSnapshot",
    "commands_extension_schema",
]
