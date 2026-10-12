"""Feature: Commands over the A2A server
Requirement: docs/specs/issue-25/requirements.md#R6

A command that changes the task (``/sub-task``, ``/model``) delivers its reply on the
sender's own stream, streaming or not.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from a2a.types import (
    CancelTaskRequest,
    Message,
    SendMessageRequest,
    StreamResponse,
    TaskState,
)
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import make_server
from tests.integration.a2a.test_server import run_to_completion, user_message
from tests.integration.durable.conftest import Harness
from tests.integration.durable.test_builtin_commands import with_builtins
from tiny_harness.harness.core import HarnessTask
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import RecordBase

pytestmark = pytest.mark.asyncio(loop_scope="module")


def ids() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return f"tq-{suffix}", f"ctx-{suffix}"


def command_replies(events: list[StreamResponse]) -> list[Message]:
    """The command replies a stream carried, on status updates (R6.2)."""
    return [
        e.status_update.status.message
        for e in events
        if e.HasField("status_update")
        and "command" in e.status_update.status.message.metadata.fields
    ]


async def test_a_command_that_changes_the_task_replies_on_the_senders_stream(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Feature: Commands over the A2A server
    Requirement: docs/specs/issue-25/requirements.md#R6
    Requirement: docs/specs/issue-25/requirements.md#R9

    Scenario: A command that changes the task replies on the sender's stream
        Given a conversation task awaiting the next message over the A2A server
        When the reporter streams "/sub-task Draft the reply"
        Then the stream carries the reply "Created sub-task <id>." with task_ref <id>
        And the stream's last event is the task listing the new sub-task
        When the reporter streams "/model model-b"
        Then the stream carries the reply naming model-b, and the task records it
        When the reporter sends "/model model-a" without streaming
        Then the returned task's status message is that reply
    """
    tq, context_id = ids()
    h = await with_builtins(Harness([scripted("Hosted reply.")]))
    server = await make_server(env, [], task_queue=tq, harness=h)
    async with server:
        tid = await run_to_completion(server, context_id)
        # A slow store write: the bridge polls while the command's persist is in flight,
        # so an event logged before it must not be mistaken for the end of the stream.
        put = h.store.put

        async def slow_put(record: RecordBase) -> None:
            await asyncio.sleep(0.2)
            await put(record)

        monkeypatch.setattr(h.store, "put", slow_put)

        async def stream(text: str) -> list[StreamResponse]:
            request = SendMessageRequest(
                message=user_message(text, context_id=context_id, task_id=tid)
            )
            return [e async for e in server.a2a().send_message(request)]

        spawned = await stream("/sub-task Draft the reply")
        changed = await stream("/model model-b")
        blocking = [
            e
            async for e in server.blocking().send_message(
                SendMessageRequest(
                    message=user_message("/model model-a", context_id=context_id, task_id=tid)
                )
            )
        ]
        await server.a2a().cancel_task(CancelTaskRequest(id=tid))
    child_id = f"{tid}.1"
    [reply] = command_replies(spawned)
    assert reply.parts[0].text.endswith(f"Created sub-task {child_id}.")
    assert reply.metadata.fields["task_ref"].string_value == child_id
    assert reply.metadata.fields["command"].string_value == "sub-task"
    assert spawned[-1].HasField("task")
    assert [r.task_id for r in HarnessTask(spawned[-1].task).ext.sub_tasks] == [child_id]
    assert spawned[-1].task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    [reply] = command_replies(changed)
    assert "model-b" in reply.parts[0].text
    assert HarnessTask(changed[-1].task).ext.model == "model-b"
    [result] = blocking
    assert result.HasField("task")
    assert "model-a" in result.task.status.message.parts[0].text
    assert result.task.status.message.metadata.fields["command"].string_value == "model"
    assert len(h.llm.requests) == 1
