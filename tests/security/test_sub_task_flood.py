"""Abuse cases 3 and 6 (issue-25) over the real A2A app: ``/sub-task`` is an ordinary
``SendMessage``, so the limits middleware rate-limits it before Temporal is touched, and a
stranger's command is answered as if the task did not exist."""

from __future__ import annotations

import uuid

import httpx
import pytest
from a2a.client.client import ClientCallContext
from a2a.types import SendMessageRequest
from a2a.utils.errors import A2AError
from google.protobuf import json_format
from pydantic import HttpUrl
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import make_server
from tests.integration.a2a.test_server import run_to_completion, user_message
from tests.integration.durable.conftest import Harness, env
from tests.integration.durable.test_builtin_commands import with_builtins
from tiny_harness.config import ServerConfig
from tiny_harness.harness.core import HarnessTask
from tiny_harness.harness.models import scripted
from tiny_harness.service.a2a import create_app
from tiny_harness.service.a2a.middleware import TOO_MANY
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]
PER_MINUTE = 3


def send_body(text: str, *, task_id: str, context_id: str) -> dict[str, object]:
    """A JSON-RPC ``SendMessage``, as any A2A client posts it."""
    request = SendMessageRequest(message=user_message(text, context_id=context_id, task_id=task_id))
    return {
        "jsonrpc": "2.0",
        "id": uuid.uuid4().hex,
        "method": "SendMessage",
        "params": json_format.MessageToDict(request),
    }


async def test_a_sub_task_flood_is_rate_limited_before_temporal(env: WorkflowEnvironment) -> None:
    """
    Feature: Security — abuse case 6
    Requirement: docs/specs/issue-25/requirements.md#security-considerations

    Scenario: /sub-task past rate_limit_per_minute gets 429 and creates nothing
        Given a conversation task awaiting the next message
        And the A2A app limited to 3 requests a minute per peer
        When one participant sends "/sub-task" 5 times in a row
        Then the first 3 create sub-tasks and the rest are answered 429
        And the task lists exactly 3 sub-tasks, and no workflow exists for a 4th
    """
    suffix = uuid.uuid4().hex[:8]
    context_id = f"ctx-{suffix}"
    h = await with_builtins(Harness([scripted("Hosted reply.")]))
    server = await make_server(env, [], task_queue=f"tq-{suffix}", harness=h)
    limited = create_app(
        server.handler,
        server.card,
        config=ServerConfig(base_url=HttpUrl("http://harness"), rate_limit_per_minute=PER_MINUTE),
    )
    async with server:
        tid = await run_to_completion(server, context_id)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=limited),
            base_url="http://harness",
            timeout=60,
            headers={"X-Participant-Id": "alice", "A2A-Version": "1.0"},
        ) as http:
            codes: list[int] = []
            for n in range(PER_MINUTE + 2):
                body = send_body(f"/sub-task piece {n}", task_id=tid, context_id=context_id)
                response = await http.post("/", json=body)
                codes.append(response.status_code)
                if response.status_code == 200:
                    assert "error" not in response.json(), response.json()
        handle = env.client.get_workflow_handle_for(TaskWorkflow.run, tid)
        parent = HarnessTask(await handle.query(TaskWorkflow.task_query))
        with pytest.raises(RPCError):  # the refused requests started no workflow
            await env.client.get_workflow_handle(f"{tid}.{PER_MINUTE + 1}").describe()
    assert codes == [200] * PER_MINUTE + [TOO_MANY] * 2
    # Each a task on this harness, created through its own A2A interface (issue-34 R7);
    # the workflows ``<tid>.<n>`` are their stand-ins, and no 4th was started.
    assert len(parent.ext.sub_tasks) == PER_MINUTE
    assert all(r.agent is None for r in parent.ext.sub_tasks)  # on this harness
    assert len(h.llm.requests) == 1


async def test_a_strangers_command_is_answered_as_if_the_task_did_not_exist(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Security — abuse case 3
    Requirement: docs/specs/issue-25/requirements.md#security-considerations

    Scenario: A stranger's command is answered as if the task did not exist
        Given a conversation task awaiting the next message
        When a participant who is not on the task sends "/model model-b" to it
        Then the answer is "task not found", and the task's model is unchanged
    """
    suffix = uuid.uuid4().hex[:8]
    context_id = f"ctx-{suffix}"
    h = await with_builtins(Harness([scripted("Hosted reply.")]))
    server = await make_server(env, [], task_queue=f"tq-{suffix}", harness=h)
    mallory = ClientCallContext(service_parameters={"X-Participant-Id": "mallory"})
    async with server:
        tid = await run_to_completion(server, context_id)
        with pytest.raises(A2AError) as refused:
            async for _ in server.a2a().send_message(
                SendMessageRequest(
                    message=user_message(
                        "/model model-b", context_id=context_id, task_id=tid, participant="mallory"
                    )
                ),
                context=mallory,
            ):
                pass
        handle = env.client.get_workflow_handle_for(TaskWorkflow.run, tid)
        task = HarnessTask(await handle.query(TaskWorkflow.task_query))
    assert "not found" in str(refused.value).lower()
    assert task.ext.model is None
