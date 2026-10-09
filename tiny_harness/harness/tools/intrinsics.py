"""The intrinsic tools' definitions and argument models (decision-004, R23.1).

Everything the harness can do beyond calling the LLM is a tool the LLM calls:
``create_plan``, ``complete_step``, ``spawn_subtask``, ``ask_participant``,
``create_task_for_participant``, ``set_participant_role``, the five skill tools and
``emit_ui``. This module holds their names, argument models and ``ToolDefinition``s
(``execution=INTRINSIC``); their JSON schemas are generated from the argument models and
committed under ``docs/a2a/ext/intrinsics/`` for the contract test. The bodies register
from the built-in plugin as the layers that own them land (skills in Layer 3, the core
loop's in Layer 4, ``emit_ui`` in Layer 7).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from tiny_harness.harness.tools.models import Execution, Idempotency, ToolDefinition
from tiny_harness.jsontypes import JsonSchema, JsonValue


class IntrinsicName(StrEnum):
    CREATE_PLAN = "create_plan"
    COMPLETE_STEP = "complete_step"
    SPAWN_SUBTASK = "spawn_subtask"
    ASK_PARTICIPANT = "ask_participant"
    CREATE_TASK_FOR_PARTICIPANT = "create_task_for_participant"
    SET_PARTICIPANT_ROLE = "set_participant_role"
    LIST_SKILLS = "list_skills"
    LOAD_SKILL = "load_skill"
    UNLOAD_SKILL = "unload_skill"
    LIST_SKILL_RESOURCES = "list_skill_resources"
    LOAD_SKILL_RESOURCE = "load_skill_resource"
    EMIT_UI = "emit_ui"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanStepArgs(_Args):
    name: str = Field(min_length=1, description="Short name of the step")
    description: str = Field(description="What the step does and what it produces")
    depends_on: tuple[str, ...] = Field(default=(), description="Names of steps this one waits for")


class CreatePlanArgs(_Args):
    """Attach a plan: a DAG of steps for the current task."""

    steps: tuple[PlanStepArgs, ...] = Field(min_length=1)


class CompleteStepArgs(_Args):
    """Record a step's output and mark it done."""

    step: str = Field(description="The step's name")
    output: str = Field(description="What the step produced, in one paragraph")


class SpawnSubtaskArgs(_Args):
    """Run a step in context isolation as a sub-task, locally or on a remote agent."""

    name: str
    goal: str
    acceptance_criteria: tuple[str, ...] = ()
    agent: str | None = Field(
        default=None, description="A registered remote agent id, or null for this harness"
    )
    step: str | None = Field(default=None, description="The step this sub-task is linked to")


class AskParticipantArgs(_Args):
    """Ask a participant for a small input, opinion or judgement call; the task waits."""

    participant_id: str
    question: str = Field(min_length=1)
    options: tuple[str, ...] = Field(default=(), description="Optional closed set of answers")


class CreateTaskForParticipantArgs(_Args):
    """Create a task assigned to a participant whose work must finish before this one can."""

    participant_id: str
    name: str
    goal: str
    acceptance_criteria: tuple[str, ...] = ()
    step: str | None = None


class ParticipantRole(StrEnum):
    ASSIGNEE = "assignee"
    REPORTER = "reporter"
    WATCHER = "watcher"
    ADMIN = "admin"


class SetParticipantRoleArgs(_Args):
    """Change a participant's role; only an admin may do this."""

    participant_id: str
    role: ParticipantRole


class ListSkillsArgs(_Args):
    """List the available skills: names and descriptions."""


class LoadSkillArgs(_Args):
    """Load a skill's instructions into the context."""

    name: str


class UnloadSkillArgs(_Args):
    """Unload a skill and its tools."""

    name: str


class ListSkillResourcesArgs(_Args):
    """List a loaded skill's scripts, references and assets."""

    name: str


class LoadSkillResourceArgs(_Args):
    """Read one resource of a loaded skill."""

    name: str
    kind: Literal["scripts", "references", "assets"]
    resource: str = Field(description="The file name within the kind's directory")


class EmitUiArgs(_Args):
    """Send A2UI messages to the surfaces (createSurface, updateComponents, ...)."""

    messages: tuple[dict[str, JsonValue], ...] = Field(min_length=1)


ARGUMENTS: dict[IntrinsicName, type[_Args]] = {
    IntrinsicName.CREATE_PLAN: CreatePlanArgs,
    IntrinsicName.COMPLETE_STEP: CompleteStepArgs,
    IntrinsicName.SPAWN_SUBTASK: SpawnSubtaskArgs,
    IntrinsicName.ASK_PARTICIPANT: AskParticipantArgs,
    IntrinsicName.CREATE_TASK_FOR_PARTICIPANT: CreateTaskForParticipantArgs,
    IntrinsicName.SET_PARTICIPANT_ROLE: SetParticipantRoleArgs,
    IntrinsicName.LIST_SKILLS: ListSkillsArgs,
    IntrinsicName.LOAD_SKILL: LoadSkillArgs,
    IntrinsicName.UNLOAD_SKILL: UnloadSkillArgs,
    IntrinsicName.LIST_SKILL_RESOURCES: ListSkillResourcesArgs,
    IntrinsicName.LOAD_SKILL_RESOURCE: LoadSkillResourceArgs,
    IntrinsicName.EMIT_UI: EmitUiArgs,
}

# Every intrinsic is idempotent to re-issue except the ones that create something.
_NOT_IDEMPOTENT = {
    IntrinsicName.SPAWN_SUBTASK,
    IntrinsicName.CREATE_TASK_FOR_PARTICIPANT,
    IntrinsicName.ASK_PARTICIPANT,
    IntrinsicName.EMIT_UI,
}


def input_schema(name: IntrinsicName) -> JsonSchema:
    schema = ARGUMENTS[name].model_json_schema()
    return cast(JsonSchema, schema)


def definition(name: IntrinsicName) -> ToolDefinition:
    args = ARGUMENTS[name]
    return ToolDefinition(
        name=name.value,
        description=(args.__doc__ or name.value).strip(),
        input_schema=input_schema(name),
        idempotency=Idempotency.NOT_IDEMPOTENT
        if name in _NOT_IDEMPOTENT
        else Idempotency.IDEMPOTENT,
        execution=Execution.INTRINSIC,
    )


def definitions() -> tuple[ToolDefinition, ...]:
    return tuple(definition(name) for name in IntrinsicName)


__all__ = [
    "ARGUMENTS",
    "AskParticipantArgs",
    "CompleteStepArgs",
    "CreatePlanArgs",
    "CreateTaskForParticipantArgs",
    "EmitUiArgs",
    "IntrinsicName",
    "ListSkillResourcesArgs",
    "ListSkillsArgs",
    "LoadSkillArgs",
    "LoadSkillResourceArgs",
    "ParticipantRole",
    "PlanStepArgs",
    "SetParticipantRoleArgs",
    "SpawnSubtaskArgs",
    "UnloadSkillArgs",
    "definition",
    "definitions",
    "input_schema",
]
