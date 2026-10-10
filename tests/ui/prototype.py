"""The events behind the states of ``design/tui-renderer.html`` (T5/T6 fixtures)."""

from __future__ import annotations

from typing import cast

from a2a.types import (
    Artifact,
    Message,
    Part,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.types import Role as A2ARole
from google.protobuf import struct_pb2

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.channels import CHANNEL_EXT_MEDIA_TYPE, ChannelMessageData
from tiny_harness.harness.core import (
    AcceptanceCriterion,
    HarnessTask,
    Participant,
    Plan,
    Role,
    Step,
    StepState,
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


__all__ = ["CARD", "CONTEXT_ID", "TASK_ID", "extension", "prototype_events"]
