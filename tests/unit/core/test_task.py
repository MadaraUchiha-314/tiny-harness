"""The task entity (R8.1-R8.3, R9.1, R9.5): the A2A task plus metadata, plans as DAGs."""

from __future__ import annotations

import pytest
from a2a.types import Message, Part, Task, TaskState
from google.protobuf import json_format

from tiny_harness.errors import PlanCycleError
from tiny_harness.harness.core import (
    TASK_EXT_KEY,
    AcceptanceCriterion,
    HarnessTask,
    Participant,
    Plan,
    Role,
    Step,
    StepState,
    TaskExtensionData,
    TaskRef,
    participant_of,
)


def ext() -> TaskExtensionData:
    return TaskExtensionData(
        name="Refund order #48213",
        type="support",
        goal="Resolve the damaged-on-arrival complaint within policy.",
        acceptance_criteria=(AcceptanceCriterion(text="Order verified"),),
        participants=(
            Participant(id="support-agent", kind="agent", role=Role.ASSIGNEE),
            Participant(id="u-1", kind="human", role=Role.REPORTER, display_name="Ravi"),
            Participant(id="ops-lead", kind="human", role=Role.ADMIN),
        ),
        plan=Plan(
            steps=(
                Step(id="verify", name="Verify order"),
                Step(id="policy", name="Look up policy", depends_on=("verify",)),
            )
        ),
    )


def test_extension_round_trips_through_the_proto_metadata() -> None:
    task = HarnessTask.new("t-1", "ctx-1", ext())
    assert task.id == "t-1" and task.context_id == "ctx-1"
    assert task.state == TaskState.TASK_STATE_SUBMITTED and task.state_name == "SUBMITTED"
    assert task.ext == ext()
    # the proto itself carries the data, as a ProtoJSON struct value under the extension key
    raw = json_format.MessageToDict(task.proto.metadata.fields[TASK_EXT_KEY])
    assert raw["name"] == "Refund order #48213" and raw["plan"]["steps"][1]["depends_on"] == [
        "verify"
    ]
    # a fresh view over the same proto bytes sees the same extension
    copy = Task()
    copy.ParseFromString(task.proto.SerializeToString())
    assert HarnessTask(copy).ext == ext()


def test_with_state_and_with_ext_return_new_views_without_mutating() -> None:
    task = HarnessTask.new("t-1", "ctx-1", ext())
    working = task.with_state(TaskState.TASK_STATE_WORKING)
    assert working.state_name == "WORKING" and task.state_name == "SUBMITTED"
    updated = working.with_ext(ext().model_copy(update={"goal": "changed"}))
    assert updated.ext.goal == "changed" and working.ext.goal.startswith("Resolve")
    assert (
        not updated.is_terminal and updated.with_state(TaskState.TASK_STATE_COMPLETED).is_terminal
    )


def test_participants_and_roles() -> None:
    data = ext()
    assert data.is_participant("u-1") and not data.is_participant("stranger")
    assert data.has_role("ops-lead", Role.ADMIN) and not data.has_role("u-1", Role.ADMIN)
    assert not data.has_role(None, Role.ADMIN)


def test_a_task_without_extension_data_raises() -> None:
    with pytest.raises(ValueError, match="extension"):
        _ = HarnessTask(Task(id="x", context_id="c")).ext


def test_plan_rejects_cycles_duplicates_and_unknown_dependencies() -> None:
    with pytest.raises(PlanCycleError, match="cycle"):
        Plan(
            steps=(
                Step(id="a", name="a", depends_on=("b",)),
                Step(id="b", name="b", depends_on=("a",)),
            )
        )
    with pytest.raises(PlanCycleError, match="duplicate"):
        Plan(steps=(Step(id="a", name="a"), Step(id="a", name="a2")))
    with pytest.raises(PlanCycleError, match="unknown"):
        Plan(steps=(Step(id="a", name="a", depends_on=("zzz",)),))


def test_plan_ready_steps_follow_dependencies() -> None:
    plan = Plan(
        steps=(
            Step(id="a", name="a"),
            Step(id="b", name="b", depends_on=("a",)),
            Step(id="c", name="c", depends_on=("a", "b")),
        )
    )
    assert [s.id for s in plan.ready()] == ["a"]
    plan = plan.with_step(
        plan.step("a").model_copy(update={"state": StepState.DONE, "output": "ok"})
    )
    assert [s.id for s in plan.ready()] == ["b"]
    assert [s.id for s in plan.unresolved()] == ["b", "c"]
    assert plan.step("a").output == "ok"
    linked = plan.step("b").model_copy(update={"linked_tasks": (TaskRef(task_id="sub-1"),)})
    assert plan.with_step(linked).step("b").linked_tasks[0].agent is None


def test_participant_of_reads_the_asserted_id_from_message_metadata() -> None:
    message = Message(message_id="m1", parts=[Part(text="hi")])
    assert participant_of(message) is None
    message.metadata.fields["participant_id"].string_value = "u-1"
    assert participant_of(message) == "u-1"
    message.metadata.fields["participant_id"].number_value = 5
    assert participant_of(message) is None
