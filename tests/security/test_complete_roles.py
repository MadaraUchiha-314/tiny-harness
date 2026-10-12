"""Abuse cases 3 and 4 for completion and cancellation: a stranger is answered as if the
task did not exist, and a ``watcher`` can neither complete nor cancel; a watcher's
completion is refused before it can interrupt a running turn (R5, design § Security)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from a2a.client.client import ClientCallContext
from a2a.types import (
    CancelTaskRequest,
    Message,
    Part,
    SendMessageConfiguration,
    SendMessageRequest,
    TaskState,
)
from a2a.types import Role as A2ARole
from a2a.utils.errors import A2AError
from google.protobuf import struct_pb2
from temporalio.client import WorkflowUpdateFailedError
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import Server, make_server
from tests.integration.durable.conftest import (
    Harness,
    awaiting_next_message,
    close,
    env,
    message,
    send,
    start,
)
from tests.integration.durable.test_complete import control
from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.harness.models import scripted
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.workflows import TaskWorkflow
from tiny_harness.service.inbox import EVENT_MEDIA_TYPE

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]
GET_ORDER = ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})


def as_(participant: str) -> ClientCallContext:
    return ClientCallContext(service_parameters={"X-Participant-Id": participant})


def watched_task(tid: str) -> HarnessTask:
    return HarnessTask.new(
        tid,
        "ctx-1",
        TaskExtensionData(
            name="Refund",
            goal="g",
            participants=(
                Participant(id="alice", kind="human", role=Role.REPORTER),
                Participant(id="wendy", kind="human", role=Role.WATCHER),
                Participant(id="agent", kind="agent", role=Role.ASSIGNEE),
            ),
            lifecycle="conversation",
        ),
    )


def first_message_with_watcher(context_id: str) -> Message:
    """A first message whose task envelope adds the watcher ``wendy``."""
    value = struct_pb2.Value()
    value.struct_value.update(
        {
            "kind": "task",
            "payload": {
                "name": "Refund",
                "goal": "refund 48213",
                "participants": [
                    {"id": "alice", "kind": "human", "role": "reporter"},
                    {"id": "wendy", "kind": "human", "role": "watcher"},
                ],
            },
        }
    )
    msg = Message(
        message_id=uuid.uuid4().hex,
        context_id=context_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(text="refund 48213"), Part(data=value, media_type=EVENT_MEDIA_TYPE)],
    )
    msg.metadata.update({"participant_id": "alice"})
    return msg


async def started(server: Server, context_id: str) -> str:
    tid = ""
    async for event in server.blocking().send_message(
        SendMessageRequest(
            message=first_message_with_watcher(context_id),
            configuration=SendMessageConfiguration(return_immediately=True),
        )
    ):
        if event.HasField("task"):
            tid = event.task.id
    assert tid
    return tid


async def test_a_stranger_cannot_complete_or_cancel(env: WorkflowEnvironment) -> None:
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(env, [scripted("Refunded.")], task_queue=f"tq-{suffix}")
    async with server:
        tid = await started(server, f"ctx-{suffix}")
        await awaiting_next_message(env.client.get_workflow_handle_for(TaskWorkflow.run, tid))
        client = server.a2a()
        with pytest.raises(A2AError) as complete:
            async for _ in client.send_message(
                SendMessageRequest(
                    message=control(task_id=tid, participant="mallory", context_id=f"ctx-{suffix}")
                ),
                context=as_("mallory"),
            ):
                pass
        with pytest.raises(A2AError) as cancel:
            await client.cancel_task(CancelTaskRequest(id=tid), context=as_("mallory"))
        task = await env.client.get_workflow_handle_for(TaskWorkflow.run, tid).query(
            TaskWorkflow.task_query
        )
    assert "not found" in str(complete.value).lower()
    assert "not found" in str(cancel.value).lower()
    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED


async def test_a_watcher_cannot_complete_or_cancel_an_idle_task(env: WorkflowEnvironment) -> None:
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(env, [scripted("Refunded.")], task_queue=f"tq-{suffix}")
    async with server:
        tid = await started(server, f"ctx-{suffix}")
        handle = env.client.get_workflow_handle_for(TaskWorkflow.run, tid)
        await awaiting_next_message(handle)
        client = server.a2a()
        with pytest.raises(A2AError) as complete:
            async for _ in client.send_message(
                SendMessageRequest(
                    message=control(task_id=tid, participant="wendy", context_id=f"ctx-{suffix}")
                ),
                context=as_("wendy"),
            ):
                pass
        with pytest.raises(A2AError) as cancel:
            await client.cancel_task(CancelTaskRequest(id=tid), context=as_("wendy"))
        task = await handle.query(TaskWorkflow.task_query)
        await close(handle)
    assert "watcher" in str(complete.value)
    assert "watcher" in str(cancel.value)
    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED


async def test_a_watcher_cannot_complete_by_naming_the_reporter_in_the_message(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Security — abuse case 4
    Requirement: docs/specs/issue-25/requirements.md#R5

    Scenario: the asserted identity, not the message's metadata, decides who completes
        Given a parked conversation where alice is the reporter and wendy a watcher
        When wendy (X-Participant-Id: wendy) sends a complete control whose metadata
            names participant_id "alice"
        Then the message is refused: it names a different participant than the request
        And the task still waits INPUT_REQUIRED
    """
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(env, [scripted("Refunded.")], task_queue=f"tq-{suffix}")
    async with server:
        tid = await started(server, f"ctx-{suffix}")
        handle = env.client.get_workflow_handle_for(TaskWorkflow.run, tid)
        await awaiting_next_message(handle)
        with pytest.raises(A2AError) as complete:
            async for _ in server.a2a().send_message(
                SendMessageRequest(
                    message=control(task_id=tid, participant="alice", context_id=f"ctx-{suffix}")
                ),
                context=as_("wendy"),
            ):
                pass
        task = await handle.query(TaskWorkflow.task_query)
        await close(handle)
    assert "different participant" in str(complete.value)
    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED


async def test_a_watchers_completion_does_not_interrupt_a_running_turn(
    env: WorkflowEnvironment,
) -> None:
    """The inbox update's validator refuses it before its handler can set the interrupt;
    the turn runs to its reply (abuse case 4)."""
    h = await Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")]).bind()
    h.get_order.gate = asyncio.Event()
    tq, tid = f"tq-{uuid.uuid4().hex[:8]}", f"t-{uuid.uuid4().hex[:8]}"
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(watched_task(tid)),
            message("refund 48213", task_id=tid, message_id="m1"),
        )
        await asyncio.wait_for(h.get_order.released.wait(), timeout=30)
        with pytest.raises(WorkflowUpdateFailedError):
            await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
                TaskWorkflow.inbox, control(task_id=tid, message_id="m2", participant="wendy")
            )
        h.get_order.gate.set()
        current = await awaiting_next_message(handle)
        await close(handle)
    assert current.proto.status.message.parts[0].text == "Refunded."
    assert len(h.llm.requests) == 2
