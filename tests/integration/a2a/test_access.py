"""Abuse case 4 over the live server: a foreign task is not found, uniformly."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from a2a.client.client import ClientCallContext
from a2a.types import (
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    SendMessageConfiguration,
    SendMessageRequest,
    SubscribeToTaskRequest,
)
from a2a.utils.errors import A2AError
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import make_server
from tests.integration.a2a.test_server import GET_ORDER, user_message
from tiny_harness.harness.models import scripted

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_foreign_task_get_list_subscribe_cancel_not_found(env: WorkflowEnvironment) -> None:
    """Every task operation answers the same not-found for a participant who is not on
    the task, for a task that does not exist, and for a message that claims the task."""
    suffix = uuid.uuid4().hex[:8]
    tq, context_id = f"tq-{suffix}", f"ctx-{suffix}"
    server = await make_server(
        env, [scripted("", tool_calls=[GET_ORDER]), scripted("Done.")], task_queue=tq
    )
    server.harness.get_order.gate = asyncio.Event()  # the task stays WORKING meanwhile
    mallory = ClientCallContext(service_parameters={"X-Participant-Id": "mallory"})
    alice = ClientCallContext(service_parameters={"X-Participant-Id": "alice"})
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
        client = server.a2a()
        mine = await client.get_task(GetTaskRequest(id=task_id), context=alice)
        assert mine.id == task_id
        with pytest.raises(A2AError) as get:
            await client.get_task(GetTaskRequest(id=task_id), context=mallory)
        with pytest.raises(A2AError) as cancel:
            await client.cancel_task(CancelTaskRequest(id=task_id), context=mallory)
        with pytest.raises(A2AError) as missing:
            await client.get_task(GetTaskRequest(id="no-such-task"), context=mallory)
        with pytest.raises(A2AError) as sub:
            async for _ in client.subscribe(SubscribeToTaskRequest(id=task_id), context=mallory):
                pass
        with pytest.raises(A2AError) as send:
            async for _ in client.send_message(
                SendMessageRequest(
                    message=user_message(
                        "mine now", task_id=task_id, context_id=context_id, participant="mallory"
                    )
                ),
                context=mallory,
            ):
                pass
        messages = [str(e.value).lower() for e in (get, cancel, missing, sub, send)]
        assert all("not found" in m for m in messages), messages
        listed = await client.list_tasks(ListTasksRequest(context_id=context_id), context=mallory)
        assert list(listed.tasks) == []
        server.harness.get_order.gate.set()
        final = await env.client.get_workflow_handle(task_id).result()
    assert final.id == task_id
