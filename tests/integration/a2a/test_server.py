"""Feature: A2A server
Requirement: docs/specs/issue-3/requirements.md#R14

The harness is an A2A 1.0 server: every verb, streaming through the durable event log.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    Message,
    Part,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    TaskPushNotificationConfig,
    TaskState,
)
from a2a.types import Role as A2ARole
from a2a.utils.errors import A2AError
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import Server, make_server
from tiny_harness.harness.core import TASK_EXT_KEY
from tiny_harness.harness.models import scripted
from tiny_harness.harness.tools import ToolCall

pytestmark = pytest.mark.asyncio(loop_scope="module")

GET_ORDER = ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})


def ids() -> tuple[str, str, str]:
    suffix = uuid.uuid4().hex[:8]
    return f"tq-{suffix}", f"task-{suffix}", f"ctx-{suffix}"


def user_message(
    text: str, *, context_id: str, task_id: str | None = None, participant: str = "alice"
) -> Message:
    """A first message names no task: A2A 1.0 has the server assign the task id."""
    msg = Message(
        message_id=uuid.uuid4().hex,
        context_id=context_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(text=text)],
    )
    if task_id is not None:
        msg.task_id = task_id
    msg.metadata.update({"participant_id": participant})
    return msg


async def run_to_completion(server: Server, context_id: str, text: str = "hello") -> str:
    """Send a first message and return the server-assigned task id once it completed."""
    task_id = ""
    async for event in server.a2a().send_message(
        SendMessageRequest(message=user_message(text, context_id=context_id))
    ):
        if event.HasField("task"):
            task_id = event.task.id
    assert task_id
    return task_id


def kind(event: StreamResponse) -> tuple[str, int | None]:
    if event.HasField("task"):
        return "task", event.task.status.state
    if event.HasField("status_update"):
        return "status_update", event.status_update.status.state
    if event.HasField("message"):
        return "message", None
    return "artifact_update", None


async def test_sendstreamingmessage_streams_a_task_then_status_updates_through_the_bridge(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: A2A server
    Requirement: docs/specs/issue-3/requirements.md#R14

    Scenario: SendStreamingMessage streams a Task then status updates through the bridge
        Given a running worker and the server in-process
        When a client sends a streaming message
        Then it receives the Task first, then WORKING, then COMPLETED with the answer
        And the task carries the tiny-harness extension in its metadata
    """
    tq, _task_id, context_id = ids()
    server = await make_server(
        env, [scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")], task_queue=tq
    )
    async with server:
        events = [
            e
            async for e in server.a2a().send_message(
                SendMessageRequest(message=user_message("refund 48213", context_id=context_id))
            )
        ]
    kinds = [kind(e) for e in events]
    assert events[0].task.id and events[0].task.context_id == context_id
    assert kinds[0] == ("task", TaskState.TASK_STATE_SUBMITTED)
    assert kinds[1] == ("status_update", TaskState.TASK_STATE_WORKING)
    assert kinds[-1] == ("status_update", TaskState.TASK_STATE_COMPLETED)
    assert events[-1].status_update.status.message.parts[0].text == "Refunded."
    assert TASK_EXT_KEY in events[0].task.metadata.fields


async def test_gettask_and_listtasks_read_the_workflow(env: WorkflowEnvironment) -> None:
    """
    Feature: A2A server
    Requirement: docs/specs/issue-3/requirements.md#R14

    Scenario: GetTask and ListTasks read the workflow
        Given a task that ran to completion
        When the client calls GetTask and ListTasks
        Then both return the task in its COMPLETED state from the workflow
    """
    tq, _task_id, context_id = ids()
    server = await make_server(env, [scripted("Done.")], task_queue=tq)
    async with server:
        task_id = await run_to_completion(server, context_id)
        task = await server.a2a().get_task(GetTaskRequest(id=task_id))
        assert task.status.state == TaskState.TASK_STATE_COMPLETED
        listed = await server.a2a().list_tasks(ListTasksRequest(context_id=context_id))
    assert [t.id for t in listed.tasks] == [task_id]


async def test_an_unadvertised_extension_is_rejected(env: WorkflowEnvironment) -> None:
    """
    Feature: A2A server
    Requirement: docs/specs/issue-3/requirements.md#R14

    Scenario: an unadvertised extension is rejected
        Given a request activating an extension the card does not advertise
        When it is sent
        Then the server answers the unsupported-operation error and no task exists
    """
    from a2a.client.client import ClientCallContext

    tq, task_id, context_id = ids()
    server = await make_server(env, [scripted("Done.")], task_queue=tq)
    async with server:
        with pytest.raises(A2AError) as info:
            async for _ in server.a2a().send_message(
                SendMessageRequest(message=user_message("hi", context_id=context_id)),
                context=ClientCallContext(
                    service_parameters={"A2A-Extensions": "https://example.com/ext/evil/v1"}
                ),
            ):
                pass
        assert "unsupported" in str(info.value).lower()
        with pytest.raises(A2AError):
            await server.a2a().get_task(GetTaskRequest(id=task_id))
    assert server.harness.llm.requests == []


async def test_returnimmediately_returns_after_the_task_exists(env: WorkflowEnvironment) -> None:
    """
    Feature: A2A server
    Requirement: docs/specs/issue-3/requirements.md#R15

    Scenario: returnImmediately returns after the task exists
        Given a tool activity that blocks
        When a non-streaming SendMessage with returnImmediately is sent
        Then it returns the task before the task completes
    """
    tq, task_id, context_id = ids()
    server = await make_server(
        env, [scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")], task_queue=tq
    )
    server.harness.get_order.gate = asyncio.Event()
    async with server:
        responses = [
            e
            async for e in server.blocking().send_message(
                SendMessageRequest(
                    message=user_message("refund 48213", context_id=context_id),
                    configuration=SendMessageConfiguration(return_immediately=True),
                )
            )
        ]
        assert responses and responses[0].HasField("task")
        assert responses[0].task.status.state != TaskState.TASK_STATE_COMPLETED
        task_id = responses[0].task.id
        server.harness.get_order.gate.set()
        task = responses[0].task
        for _ in range(100):
            task = await server.a2a().get_task(GetTaskRequest(id=task_id))
            if task.status.state == TaskState.TASK_STATE_COMPLETED:
                break
            await asyncio.sleep(0.1)
        assert task.status.state == TaskState.TASK_STATE_COMPLETED


async def test_push_notification_configs_receive_status_updates(env: WorkflowEnvironment) -> None:
    """
    Feature: A2A server
    Requirement: docs/specs/issue-3/requirements.md#R15

    Scenario: push notification configs receive status updates
        Given a task waiting in a tool activity and a push config registered for it
        When the task completes
        Then the config's URL receives the COMPLETED status update with the token header
        And the token is not stored in clear
    """
    from tiny_harness.harness.persistence import Filter, PushConfigRecord

    tq, task_id, context_id = ids()
    server = await make_server(
        env, [scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")], task_queue=tq
    )
    server.harness.get_order.gate = asyncio.Event()
    async with server:
        responses = [
            e
            async for e in server.blocking().send_message(
                SendMessageRequest(
                    message=user_message("refund 48213", context_id=context_id),
                    configuration=SendMessageConfiguration(return_immediately=True),
                )
            )
        ]
        assert responses
        task_id = responses[0].task.id
        await server.a2a().create_task_push_notification_config(
            TaskPushNotificationConfig(
                task_id=task_id, url="http://push.test/hook", token="t0k3n-secret"
            )
        )
        server.harness.get_order.gate.set()
        for _ in range(100):
            if any(b"TASK_STATE_COMPLETED" in r.content for r in server.pushes):
                break
            await asyncio.sleep(0.1)
    completed = [r for r in server.pushes if b"TASK_STATE_COMPLETED" in r.content]
    assert completed and completed[0].url.host == "push.test"
    assert completed[0].headers.get("X-A2A-Notification-Token") == "t0k3n-secret"
    records = await server.harness.store.query(PushConfigRecord, Filter(task_id=task_id))
    assert records and "t0k3n-secret" not in records[0].token_ciphertext


async def test_cancel_emits_canceled(env: WorkflowEnvironment) -> None:
    """
    Feature: A2A server
    Requirement: docs/specs/issue-3/requirements.md#R14

    Scenario: cancel emits CANCELED
        Given a task blocked in a tool activity
        When the client cancels it
        Then the response is the task in CANCELED and the workflow is closed
    """
    tq, task_id, context_id = ids()
    server = await make_server(
        env, [scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")], task_queue=tq
    )
    server.harness.get_order.gate = asyncio.Event()
    async with server:
        task_id = ""
        async for event in server.blocking().send_message(
            SendMessageRequest(
                message=user_message("refund 48213", context_id=context_id),
                configuration=SendMessageConfiguration(return_immediately=True),
            )
        ):
            if event.HasField("task"):
                task_id = event.task.id
        assert task_id
        await asyncio.wait_for(server.harness.get_order.released.wait(), timeout=30)
        task = await server.a2a().cancel_task(CancelTaskRequest(id=task_id))
        assert task.status.state == TaskState.TASK_STATE_CANCELED
        server.harness.get_order.gate.set()
        final = await env.client.get_workflow_handle(task_id).result()
    assert final.status.state == TaskState.TASK_STATE_CANCELED


async def test_subscribetotask_after_a_server_restart_replays_the_event_log(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: A2A server
    Requirement: docs/specs/issue-3/requirements.md#R14

    Scenario: SubscribeToTask after a server restart replays the event log
        Given a task that completed under one server process
        When a fresh server process serves SubscribeToTask for it
        Then the client receives the task and every status update from sequence 0
    """
    tq, _task_id, context_id = ids()
    first = await make_server(env, [scripted("Done.")], task_queue=tq)
    async with first:
        task_id = await run_to_completion(first, context_id)
        await env.client.get_workflow_handle(task_id).result()  # the final persist has run
    second = await make_server(env, [], task_queue=tq, harness=first.harness)
    async with second:
        events = [e async for e in second.a2a().subscribe(SubscribeToTaskRequest(id=task_id))]
    kinds = [kind(e) for e in events]
    assert kinds[0][0] == "task"
    assert ("status_update", TaskState.TASK_STATE_WORKING) in kinds
    assert kinds[-1] == ("status_update", TaskState.TASK_STATE_COMPLETED)
