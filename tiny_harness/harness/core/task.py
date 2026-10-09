"""The task entity: the A2A task, extended through its metadata (R8.1-R8.3, R9).

``a2a.types.Task`` is a protobuf message and cannot be subclassed, so the attributes A2A
lacks (name, type, goal, description, acceptance criteria, participants, parent and
sub-task links, the plan) live in ``Task.metadata`` under ``TASK_EXT_KEY`` as
``TaskExtensionData``, and ``HarnessTask`` is a typed view over one proto that reads and
writes them. The A2A task state (``proto.status.state``) is the authoritative state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self, cast

from a2a.types import Task, TaskState, TaskStatus
from google.protobuf import json_format, struct_pb2
from pydantic import BaseModel, ConfigDict, model_validator

from tiny_harness.errors import PlanCycleError
from tiny_harness.harness.entities import EntityRef
from tiny_harness.jsontypes import JsonObject

TASK_EXT_KEY = "io.github.madarauchiha-314.tiny-harness/task"
TASK_EXT_URI = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/task/v1"
TASK_EXT_MEDIA_TYPE = "application/vnd.tiny-harness.task+json"


class Role(StrEnum):
    ASSIGNEE = "assignee"
    REPORTER = "reporter"
    WATCHER = "watcher"
    ADMIN = "admin"


class Participant(BaseModel, frozen=True):
    """A human or agent with a role on the task (R8.1)."""

    id: str
    kind: Literal["human", "agent"]
    role: Role
    display_name: str = ""


class TaskRef(BaseModel, frozen=True):
    """A task on this harness (``agent`` is None) or on a remote agent."""

    task_id: str
    agent: EntityRef | None = None


class AcceptanceCriterion(BaseModel, frozen=True):
    text: str
    met: bool = False


class StepState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"


class Step(BaseModel, frozen=True):
    """One node of the plan DAG (R9.1)."""

    id: str
    name: str
    description: str = ""
    depends_on: tuple[str, ...] = ()
    output: str | None = None
    linked_tasks: tuple[TaskRef, ...] = ()
    state: StepState = StepState.PENDING


class Plan(BaseModel, frozen=True):
    """A DAG of steps; a cycle or a dangling dependency is a ``PlanCycleError`` (R9.5)."""

    steps: tuple[Step, ...]

    @model_validator(mode="after")
    def _acyclic(self) -> Self:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise PlanCycleError("duplicate step ids", steps=",".join(ids))
        by_id = {s.id: s for s in self.steps}
        for step in self.steps:
            for dep in step.depends_on:
                if dep not in by_id:
                    raise PlanCycleError(
                        "step depends on an unknown step", step=step.id, depends_on=dep
                    )
        state: dict[str, int] = {}

        def visit(step_id: str, trail: tuple[str, ...]) -> None:
            if state.get(step_id) == 2:
                return
            if state.get(step_id) == 1:
                raise PlanCycleError("plan has a cycle", cycle=" -> ".join((*trail, step_id)))
            state[step_id] = 1
            for dep in by_id[step_id].depends_on:
                visit(dep, (*trail, step_id))
            state[step_id] = 2

        for step in self.steps:
            visit(step.id, ())
        return self

    def step(self, step_id: str) -> Step:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise PlanCycleError("no such step", step=step_id)

    def ready(self) -> tuple[Step, ...]:
        """Pending steps whose dependencies are all done."""
        done = {s.id for s in self.steps if s.state is StepState.DONE}
        return tuple(
            s for s in self.steps if s.state is StepState.PENDING and set(s.depends_on) <= done
        )

    def with_step(self, updated: Step) -> Plan:
        return Plan(steps=tuple(updated if s.id == updated.id else s for s in self.steps))

    def unresolved(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.state in (StepState.PENDING, StepState.ACTIVE))


class TaskExtensionData(BaseModel, frozen=True):
    """What A2A's task lacks (R8.1); carried in ``Task.metadata[TASK_EXT_KEY]``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: str | None = None
    goal: str
    description: str = ""
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = ()
    participants: tuple[Participant, ...] = ()
    parent_tasks: tuple[TaskRef, ...] = ()
    sub_tasks: tuple[TaskRef, ...] = ()
    plan: Plan | None = None

    def participant(self, participant_id: str) -> Participant | None:
        for p in self.participants:
            if p.id == participant_id:
                return p
        return None

    def is_participant(self, participant_id: str | None) -> bool:
        return participant_id is not None and self.participant(participant_id) is not None

    def has_role(self, participant_id: str | None, role: Role) -> bool:
        p = self.participant(participant_id) if participant_id else None
        return p is not None and p.role is role


TERMINAL_STATES: frozenset[int] = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
    }
)


def state_name(state: int) -> str:
    """``TASK_STATE_WORKING`` → ``WORKING``."""
    return TaskState.Name(state).removeprefix("TASK_STATE_")


class HarnessTask:
    """A typed view over one ``a2a.types.Task``; nothing is duplicated (R8.2, R8.3)."""

    def __init__(self, proto: Task) -> None:
        self.proto = proto

    @classmethod
    def new(cls, task_id: str, context_id: str, ext: TaskExtensionData) -> HarnessTask:
        proto = Task(
            id=task_id,
            context_id=context_id,
            status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
        )
        return cls(proto).with_ext(ext)

    @property
    def id(self) -> str:
        return self.proto.id

    @property
    def context_id(self) -> str:
        return self.proto.context_id

    @property
    def state(self) -> int:
        return self.proto.status.state

    @property
    def state_name(self) -> str:
        return state_name(self.state)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def ext(self) -> TaskExtensionData:
        fields = self.proto.metadata.fields
        if TASK_EXT_KEY not in fields:
            raise ValueError("task carries no tiny-harness extension data")
        raw = cast(JsonObject, json_format.MessageToDict(fields[TASK_EXT_KEY]))
        return TaskExtensionData.model_validate(raw)

    def with_ext(self, ext: TaskExtensionData) -> HarnessTask:
        proto = Task()
        proto.CopyFrom(self.proto)
        value = struct_pb2.Value()
        json_format.ParseDict(ext.model_dump(mode="json"), value)
        proto.metadata.fields[TASK_EXT_KEY].CopyFrom(value)
        return HarnessTask(proto)

    def with_state(self, state: int) -> HarnessTask:
        proto = Task()
        proto.CopyFrom(self.proto)
        proto.status.CopyFrom(
            TaskStatus(state=cast(TaskState, state), message=proto.status.message)
        )
        return HarnessTask(proto)

    def ext_json(self) -> JsonObject:
        return cast(JsonObject, self.ext.model_dump(mode="json"))


__all__ = [
    "TASK_EXT_KEY",
    "TASK_EXT_MEDIA_TYPE",
    "TASK_EXT_URI",
    "TERMINAL_STATES",
    "AcceptanceCriterion",
    "HarnessTask",
    "Participant",
    "Plan",
    "Role",
    "Step",
    "StepState",
    "TaskExtensionData",
    "TaskRef",
    "state_name",
]
