"""The events behind the states of ``design/tui-renderer.html`` and issue-25's
``design/tui-task-controls.html`` (T5/T6 fixtures)."""

from __future__ import annotations

from typing import cast

from a2a.types import (
    Artifact,
    Message,
    Part,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.types import Role as A2ARole
from google.protobuf import struct_pb2

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.channels import CHANNEL_EXT_MEDIA_TYPE, ChannelMessageData
from tiny_harness.harness.commands import CommandSpec
from tiny_harness.harness.core import (
    STATUS_EXT_KEY,
    AcceptanceCriterion,
    HarnessTask,
    Participant,
    Plan,
    Role,
    Step,
    StepState,
    SubState,
    TaskExtensionData,
    TaskRef,
)
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.interaction.a2ui import A2UI_MEDIA_TYPE, A2UI_VERSION, BASIC_CATALOG_ID
from tiny_harness.jsontypes import JsonObject

TASK_ID = "7f3a0000-0000-0000-0000-00000000c21e"
CONTEXT_ID = "ctx-7f3a"


def data_part(payload: JsonObject, media_type: str) -> Part:
    value = struct_pb2.Value()
    value.struct_value.update(payload)
    return Part(data=value, media_type=media_type)


def extension() -> TaskExtensionData:
    return TaskExtensionData(
        name="Refund order #48213",
        goal="Resolve the damaged-on-arrival complaint on order #48213 within policy.",
        acceptance_criteria=(
            AcceptanceCriterion(text="Order and warranty verified", met=True),
            AcceptanceCriterion(text="Policy applied and cited", met=True),
            AcceptanceCriterion(text="Customer offered a resolution they accept"),
            AcceptanceCriterion(text="Ticket closed with the resolution recorded"),
        ),
        participants=(
            Participant(id="support-agent", kind="agent", role=Role.ASSIGNEE),
            Participant(id="you", kind="human", role=Role.REPORTER),
            Participant(id="billing-agent", kind="agent", role=Role.WATCHER),
            Participant(id="ops-lead", kind="human", role=Role.ADMIN),
        ),
        sub_tasks=(
            TaskRef(task_id="t-91a0", agent=EntityRef(kind=EntityKind.AGENT, id="billing-agent")),
        ),
        plan=Plan(
            steps=(
                Step(
                    id="verify",
                    name="Verify order and delivery",
                    state=StepState.DONE,
                    output="delivered 2026-10-06",
                ),
                Step(
                    id="policy",
                    name="Look up damage policy",
                    state=StepState.DONE,
                    output="refund or replacement",
                ),
                Step(
                    id="agree",
                    name="Agree resolution with customer",
                    state=StepState.ACTIVE,
                    depends_on=("policy",),
                ),
                Step(
                    id="close",
                    name="Record resolution and close",
                    depends_on=("agree",),
                ),
            )
        ),
    )


def status(state: int, message: Message | None = None) -> TaskStatusUpdateEvent:
    return TaskStatusUpdateEvent(
        task_id=TASK_ID,
        context_id=CONTEXT_ID,
        status=TaskStatus(state=cast(TaskState, state), message=message),
    )


def agent_text(text: str, message_id: str) -> Message:
    return Message(
        message_id=message_id,
        task_id=TASK_ID,
        context_id=CONTEXT_ID,
        role=A2ARole.ROLE_AGENT,
        parts=[Part(text=text)],
    )


CARD: JsonObject = {
    "version": A2UI_VERSION,
    "updateComponents": {
        "surfaceId": "resolution",
        "components": [
            {"id": "root", "component": "Card", "child": "col"},
            {"id": "col", "component": "Column", "children": ["title", "pick", "ok"]},
            {"id": "title", "component": "Text", "text": "Proposed resolution"},
            {
                "id": "pick",
                "component": "ChoicePicker",
                "label": "Resolution",
                "options": [
                    {"label": "Ship replacement now", "value": "replace"},
                    {"label": "Refund after photo", "value": "refund"},
                    {"label": "Escalate to a human", "value": "escalate"},
                ],
                "value": {"path": "/choice"},
            },
            {
                "id": "ok",
                "component": "Button",
                "child": "ok-label",
                "action": {
                    "event": {"name": "confirm", "context": {"choice": {"path": "/choice"}}}
                },
            },
            {"id": "ok-label", "component": "Text", "text": "Confirm"},
        ],
    },
}


def prototype_events() -> list[A2AEvent]:
    """The conversation of the prototype's first state, as the A2A events behind it."""
    task = HarnessTask.new(TASK_ID, CONTEXT_ID, extension()).proto
    task.status.CopyFrom(TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
    create: JsonObject = {
        "version": A2UI_VERSION,
        "createSurface": {"surfaceId": "resolution", "catalogId": BASIC_CATALOG_ID},
    }
    ui = TaskArtifactUpdateEvent(
        task_id=TASK_ID,
        context_id=CONTEXT_ID,
        artifact=Artifact(
            artifact_id="a2ui:1",
            name="a2ui",
            parts=[data_part(create, A2UI_MEDIA_TYPE), data_part(CARD, A2UI_MEDIA_TYPE)],
        ),
        last_chunk=True,
    )
    help_data = ChannelMessageData(
        channel_id=TASK_ID,
        sender="support-agent",
        kind="help_request",
        text=(
            "The customer has two open orders. Should the replacement go to the address "
            "on #48213 or the newer address on #48377?"
        ),
    )
    help_message = Message(
        message_id="help-1",
        task_id=TASK_ID,
        context_id=CONTEXT_ID,
        role=A2ARole.ROLE_AGENT,
        parts=[
            Part(text=help_data.text),
            data_part(help_data.model_dump(mode="json"), CHANNEL_EXT_MEDIA_TYPE),
        ],
    )
    unrenderable = TaskArtifactUpdateEvent(
        task_id=TASK_ID,
        context_id=CONTEXT_ID,
        artifact=Artifact(
            artifact_id="cal-1",
            name="calendar",
            parts=[data_part({"when": "2026-10-10"}, "application/vnd.example.calendar+json")],
        ),
        last_chunk=True,
    )
    return [
        task,
        status(TaskState.TASK_STATE_WORKING),
        status(
            TaskState.TASK_STATE_WORKING,
            agent_text(
                "The order qualifies for a damaged-on-arrival resolution. The item is $129, "
                "so policy needs a photo before a refund. A replacement can ship without one.",
                "m-agent-1",
            ),
        ),
        ui,
        status(TaskState.TASK_STATE_INPUT_REQUIRED, help_message),
        unrenderable,
    ]


# --- issue-25: task controls (``design/tui-task-controls.html``) ---------------------------

SUB_TASK_ID = "9b210000-0000-0000-0000-00000000d4e5"
AWAITING_NEXT = "awaiting-next-message"

COMMANDS = (
    CommandSpec(
        name="model", description="show or switch the model for this task", argument_hint="[name]"
    ),
    CommandSpec(
        name="effort", description="show or set reasoning effort", argument_hint="[low|medium|high]"
    ),
    CommandSpec(name="status", description="state, settings, plan and sub-tasks"),
    CommandSpec(
        name="sub-task",
        description="split off a sub-task of this task",
        argument_hint="<description>",
    ),
)


def conversation_extension(sub_tasks: tuple[TaskRef, ...] = ()) -> TaskExtensionData:
    return TaskExtensionData(
        name="Support triage",
        goal="Summarise the open support tickets and suggest owners.",
        participants=(
            Participant(id="assistant", kind="agent", role=Role.ASSIGNEE),
            Participant(id="alice", kind="human", role=Role.REPORTER),
        ),
        sub_tasks=sub_tasks,
        lifecycle="conversation",
        model="gpt-6.1-sol",
    )


def with_sub_state(task: Task, sub_state: str) -> Task:
    value = struct_pb2.Value()
    value.struct_value.update({"sub_state": sub_state})
    task.metadata.fields[STATUS_EXT_KEY].CopyFrom(value)
    return task


def parked(
    message: Message | None = None, *, task_id: str = TASK_ID, sub_state: str = AWAITING_NEXT
) -> TaskStatusUpdateEvent:
    """``INPUT_REQUIRED`` with the status extension's sub-state in the update's metadata."""
    event = TaskStatusUpdateEvent(
        task_id=task_id,
        context_id=CONTEXT_ID,
        status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED, message=message),
    )
    event.metadata.update({STATUS_EXT_KEY: {"sub_state": sub_state}})
    return event


def conversation_task(sub_tasks: tuple[TaskRef, ...] = ()) -> Task:
    task = HarnessTask.new(TASK_ID, CONTEXT_ID, conversation_extension(sub_tasks)).proto
    task.status.CopyFrom(TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED))
    return with_sub_state(task, AWAITING_NEXT)


def conversation_events() -> list[A2AEvent]:
    """The prototype's first state: a reply arrived and the conversation waits for you."""
    task = HarnessTask.new(TASK_ID, CONTEXT_ID, conversation_extension()).proto
    task.status.CopyFrom(TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
    you = Message(
        message_id="m-you-1",
        task_id=TASK_ID,
        context_id=CONTEXT_ID,
        role=A2ARole.ROLE_USER,
        parts=[
            Part(text="Summarise the three open support tickets and suggest who should take each.")
        ],
    )
    reply = agent_text(
        "#48213 (damaged blender): billing — refund needs a photo.\n"
        "#48377 (address change): logistics.\n"
        "#48402 (login loop): platform on-call.",
        "m-agent-1",
    )
    return [
        you,
        task,
        status(TaskState.TASK_STATE_WORKING),
        status(TaskState.TASK_STATE_WORKING, reply),
        parked(),
    ]


def command_reply(
    text: str, *, command: str, task_ref: str | None = None, close_client: bool = False
) -> Message:
    message = agent_text(text, f"{TASK_ID}:command:1")
    metadata = {"command": command} | ({"task_ref": task_ref} if task_ref else {})
    metadata |= {"close_client": "true"} if close_client else {}
    message.metadata.update(metadata)
    return message


def sub_task_events() -> list[A2AEvent]:
    """What ``/sub-task Draft the reply`` streams back: the command's reply on the
    re-emitted status update, then the parent with its new sub-task, whose row carries
    the state the sub-task told it (R5.6)."""
    ref = TaskRef(task_id=SUB_TASK_ID, state="INPUT_REQUIRED", sub_state=SubState(AWAITING_NEXT))
    return [
        parked(
            command_reply(
                f"Created sub-task {SUB_TASK_ID}.", command="sub-task", task_ref=SUB_TASK_ID
            )
        ),
        conversation_task((ref,)),
    ]


def sub_task() -> Task:
    """The sub-task ``/sub-task Draft the reply`` created: a conversation awaiting you."""
    ext = conversation_extension().model_copy(
        update={
            "name": "Draft the reply",
            "goal": "Draft the reply",
            "parent_tasks": (TaskRef(task_id=TASK_ID),),
        }
    )
    task = HarnessTask.new(SUB_TASK_ID, CONTEXT_ID, ext).proto
    task.status.CopyFrom(TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED))
    return with_sub_state(task, AWAITING_NEXT)


def completed_events() -> list[A2AEvent]:
    """What ``ctrl+d`` streams back: the final ``COMPLETED`` update."""
    return [status(TaskState.TASK_STATE_COMPLETED, agent_text("completed by alice", "m-done"))]


__all__ = [
    "AWAITING_NEXT",
    "CARD",
    "COMMANDS",
    "CONTEXT_ID",
    "SUB_TASK_ID",
    "TASK_ID",
    "command_reply",
    "completed_events",
    "conversation_events",
    "conversation_task",
    "extension",
    "parked",
    "prototype_events",
    "sub_task",
    "sub_task_events",
]
