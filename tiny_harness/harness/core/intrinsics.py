"""The core intrinsics' bodies (decision-004, R8.4, R9.2, R9.3, R12.2, R12.3, abuse case 2).

``create_plan``, ``complete_step``, ``spawn_subtask``, ``ask_participant``,
``create_task_for_participant``, ``set_participant_role`` and the ``emit_ui`` placeholder
are tools bound to a ``TaskContext`` (the current task and the asserted actor). Each
validates its arguments, checks what it must (an admin for a role change), and returns a
``WorkflowCommand`` the loop applies deterministically. The command's ``result`` is what
the LLM reads next turn.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import cast

from pydantic import ValidationError

from tiny_harness.errors import PlanCycleError
from tiny_harness.harness.core.task import HarnessTask, Plan, Role, Step, StepState, TaskRef
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.tools.intrinsics import (
    ARGUMENTS,
    AskParticipantArgs,
    CompleteStepArgs,
    CreatePlanArgs,
    CreateTaskForParticipantArgs,
    EmitUiArgs,
    IntrinsicName,
    SetParticipantRoleArgs,
    SpawnSubtaskArgs,
    definition,
)
from tiny_harness.harness.tools.models import Tool, ToolCall, ToolResult, WorkflowCommand
from tiny_harness.interaction.a2ui import A2UIValidationError, parse_server_message
from tiny_harness.jsontypes import JsonObject, JsonValue

_CURRENT_TASK: ContextVar[HarnessTask | None] = ContextVar("tiny_harness_task", default=None)
_CURRENT_ACTOR: ContextVar[str | None] = ContextVar("tiny_harness_actor", default=None)


class TaskContext:
    """What an intrinsic may see: the task as it stands and who is acting (self-asserted).

    Both live in context variables, so concurrent activities on one worker (one asyncio
    task each) never see each other's task: the host rebinds ``task`` before every
    operation; ``actor`` is the participant the current request asserted, or ``None``
    when nobody did (R13.3, abuse case 8).
    """

    def __init__(self, task: HarnessTask | None = None, actor: str | None = None) -> None:
        if task is not None:
            self.task = task
        if actor is not None:
            self.actor = actor

    @property
    def task(self) -> HarnessTask | None:
        return _CURRENT_TASK.get()

    @task.setter
    def task(self, value: HarnessTask | None) -> None:
        _CURRENT_TASK.set(value)

    @property
    def actor(self) -> str | None:
        return _CURRENT_ACTOR.get()

    @actor.setter
    def actor(self, value: str | None) -> None:
        _CURRENT_ACTOR.set(value)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "step"


def plan_from_args(args: CreatePlanArgs) -> Plan:
    names = {s.name: slug(s.name) for s in args.steps}
    steps = tuple(
        Step(
            id=names[s.name],
            name=s.name,
            description=s.description,
            depends_on=tuple(names.get(d, slug(d)) for d in s.depends_on),
        )
        for s in args.steps
    )
    return Plan(steps=steps)


class _CoreIntrinsic(Tool):
    def __init__(self, name: IntrinsicName, context: TaskContext) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.TOOL, id=name.value, version=None), definition(name)
        )
        self._name = name
        self._context = context

    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand:
        try:
            args = ARGUMENTS[self._name].model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult.error(call.call_id, "tool.invalid_arguments", str(exc))
        cid = call.call_id
        task = self._context.task
        if task is None:
            return ToolResult.error(cid, "tool.unbound", "no task is bound to this intrinsic")
        ext = task.ext
        if self._name is IntrinsicName.CREATE_PLAN:
            try:
                plan = plan_from_args(cast(CreatePlanArgs, args))
            except PlanCycleError as exc:
                return ToolResult.error(cid, exc.code, str(exc))
            return WorkflowCommand(
                kind="attach_plan",
                call_id=cid,
                payload=cast(JsonObject, plan.model_dump(mode="json")),
                result=ToolResult.text(cid, f"plan attached with {len(plan.steps)} steps"),
            )
        if self._name is IntrinsicName.COMPLETE_STEP:
            a = cast(CompleteStepArgs, args)
            if ext.plan is None:
                return ToolResult.error(cid, "plan.missing", "no plan; call create_plan first")
            step_id = a.step if any(s.id == a.step for s in ext.plan.steps) else slug(a.step)
            if not any(s.id == step_id for s in ext.plan.steps):
                return ToolResult.error(cid, "plan.unknown_step", f"no such step: {a.step}")
            return WorkflowCommand(
                kind="complete_step",
                call_id=cid,
                payload={"step": step_id, "output": a.output},
                result=ToolResult.text(cid, f"step {step_id} done"),
            )
        if self._name is IntrinsicName.ASK_PARTICIPANT:
            a = cast(AskParticipantArgs, args)
            if not ext.is_participant(a.participant_id):
                return ToolResult.error(
                    cid, "channel.not_a_member", "no such participant on this task"
                )
            return WorkflowCommand(
                kind="wait_for_reply",
                call_id=cid,
                payload={
                    "participant_id": a.participant_id,
                    "question": a.question,
                    "options": list(a.options),
                },
                result=ToolResult.text(cid, f"asked {a.participant_id}; waiting for the reply"),
            )
        if self._name is IntrinsicName.CREATE_TASK_FOR_PARTICIPANT:
            a = cast(CreateTaskForParticipantArgs, args)
            if not ext.is_participant(a.participant_id):
                return ToolResult.error(
                    cid, "channel.not_a_member", "no such participant on this task"
                )
            return WorkflowCommand(
                kind="create_participant_task",
                call_id=cid,
                payload={
                    "participant_id": a.participant_id,
                    "name": a.name,
                    "goal": a.goal,
                    "acceptance_criteria": list(a.acceptance_criteria),
                    "step": a.step,
                },
                result=ToolResult.text(cid, f"task for {a.participant_id} created"),
            )
        if self._name is IntrinsicName.SPAWN_SUBTASK:
            a = cast(SpawnSubtaskArgs, args)
            return WorkflowCommand(
                kind="spawn_subtask",
                call_id=cid,
                payload={
                    "name": a.name,
                    "goal": a.goal,
                    "acceptance_criteria": list(a.acceptance_criteria),
                    "agent": a.agent,
                    "step": a.step,
                },
                result=ToolResult.text(cid, f"sub-task {a.name} spawned"),
            )
        if self._name is IntrinsicName.SET_PARTICIPANT_ROLE:
            a = cast(SetParticipantRoleArgs, args)
            if not ext.has_role(self._context.actor, Role.ADMIN):
                return ToolResult.error(
                    cid, "channel.not_a_member", "only an admin may change roles"
                )
            if not ext.is_participant(a.participant_id):
                return ToolResult.error(
                    cid, "channel.not_a_member", "no such participant on this task"
                )
            return WorkflowCommand(
                kind="set_role",
                call_id=cid,
                payload={"participant_id": a.participant_id, "role": a.role.value},
                result=ToolResult.text(cid, f"{a.participant_id} is now {a.role.value}"),
            )
        a = cast(EmitUiArgs, args)
        validated: list[JsonObject] = []
        for raw in a.messages:
            try:
                validated.append(parse_server_message(dict(raw)).payload())
            except A2UIValidationError as exc:
                return ToolResult.error(cid, exc.code, str(exc))
        return WorkflowCommand(
            kind="ui_emitted",
            call_id=cid,
            payload={"messages": cast(JsonValue, validated)},
            result=ToolResult.text(cid, f"{len(validated)} UI message(s) emitted"),
        )


CORE_INTRINSICS: tuple[IntrinsicName, ...] = (
    IntrinsicName.CREATE_PLAN,
    IntrinsicName.COMPLETE_STEP,
    IntrinsicName.SPAWN_SUBTASK,
    IntrinsicName.ASK_PARTICIPANT,
    IntrinsicName.CREATE_TASK_FOR_PARTICIPANT,
    IntrinsicName.SET_PARTICIPANT_ROLE,
    IntrinsicName.EMIT_UI,
)


def core_intrinsics(context: TaskContext) -> tuple[Tool, ...]:
    return tuple(_CoreIntrinsic(name, context) for name in CORE_INTRINSICS)


# --- applying commands to the task (pure; the workflow runs this) -------------------------


def apply_to_task(task: HarnessTask, command: WorkflowCommand) -> HarnessTask:
    """The deterministic effect of a command on the task; state effects are the loop's."""
    ext = task.ext
    if command.kind == "attach_plan":
        return task.with_ext(ext.model_copy(update={"plan": Plan.model_validate(command.payload)}))
    if command.kind == "complete_step" and ext.plan is not None:
        step_id = str(command.payload["step"])
        step = ext.plan.step(step_id)
        done = step.model_copy(
            update={"state": StepState.DONE, "output": str(command.payload.get("output", ""))}
        )
        return task.with_ext(ext.model_copy(update={"plan": ext.plan.with_step(done)}))
    if command.kind == "set_role":
        pid = str(command.payload["participant_id"])
        role = Role(str(command.payload["role"]))
        participants = tuple(
            p.model_copy(update={"role": role}) if p.id == pid else p for p in ext.participants
        )
        return task.with_ext(ext.model_copy(update={"participants": participants}))
    return task


def link_subtask(task: HarnessTask, ref: TaskRef, step_id: str | None) -> HarnessTask:
    """Record a spawned child on the task and on the step it was linked to (R9.3)."""
    ext = task.ext
    update: dict[str, object] = {"sub_tasks": (*ext.sub_tasks, ref)}
    if step_id and ext.plan is not None and any(s.id == step_id for s in ext.plan.steps):
        step = ext.plan.step(step_id)
        linked = step.model_copy(update={"linked_tasks": (*step.linked_tasks, ref)})
        update["plan"] = ext.plan.with_step(linked)
    return task.with_ext(ext.model_copy(update=update))


__all__ = [
    "CORE_INTRINSICS",
    "TaskContext",
    "apply_to_task",
    "core_intrinsics",
    "link_subtask",
    "plan_from_args",
    "slug",
]
