"""The inbox handler's interrupt flag (critic round 1, A3): an incoming message can set
the interrupt, never clear one a completion set (issue-25 R5.2)."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import cast

from a2a.types import Message, Part
from a2a.types import Role as A2ARole
from google.protobuf import struct_pb2

from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.service.durable.workflows import TaskWorkflow
from tiny_harness.service.inbox import EVENT_MEDIA_TYPE


def a_message(mid: str, *, interrupt: bool | None = None, control: bool = False) -> Message:
    msg = Message(message_id=mid, task_id="t-1", role=A2ARole.ROLE_USER, parts=[Part(text="x")])
    if control:
        value = struct_pb2.Value()
        value.struct_value.update({"kind": "control", "action": "complete"})
        msg.parts[0].CopyFrom(Part(data=value, media_type=EVENT_MEDIA_TYPE))
    msg.metadata.update({"participant_id": "alice"})
    if interrupt is not None:
        msg.metadata.update({"interrupt": interrupt})
    return msg


async def deliver(wf: TaskWorkflow, message: Message) -> None:
    """Call the ``inbox`` update handler directly, as the worker would."""
    await cast(Awaitable[object], TaskWorkflow.inbox(wf, message))


def workflow_with_a_task() -> TaskWorkflow:
    wf = TaskWorkflow()
    wf.task = HarnessTask.new(
        "t-1",
        "ctx-1",
        TaskExtensionData(
            name="n",
            goal="g",
            participants=(Participant(id="alice", kind="human", role=Role.REPORTER),),
        ),
    )
    return wf


async def test_a_later_interrupt_false_does_not_clear_a_completions_interrupt() -> None:
    """
    Feature: Participant completion
    Scenario: a completion's interrupt survives a later message that says interrupt=false
        Given a workflow that accepted a complete control (which cuts the turn)
        When a message with metadata interrupt=false arrives before the cut is seen
        Then the interrupt is still set
    """
    wf = workflow_with_a_task()
    await deliver(wf, a_message("c-1", control=True))
    await deliver(wf, a_message("m-2", interrupt=False))
    assert wf.interrupted


async def test_a_message_can_still_request_an_interrupt() -> None:
    wf = workflow_with_a_task()
    await deliver(wf, a_message("m-1", interrupt=True))
    assert wf.interrupted
