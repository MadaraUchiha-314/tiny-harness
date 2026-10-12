"""Feature: Commands and subscriptions over the A2A server
Requirement: docs/specs/issue-25/requirements.md#R6

A command that changes the task (``/sub-task``, ``/model``) delivers its reply on the
sender's own stream, streaming or not, and a ``SubscribeToTask`` on a parked conversation
stays attached for what happens next.
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
    SubscribeToTaskRequest,
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


async def test_a_subscriber_to_a_parked_conversation_stays_attached(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: SubscribeToTask
    Requirement: docs/specs/issue-25/requirements.md#R5
    Requirement: docs/specs/issue-3/requirements.md#R20

    Scenario: A subscriber to a parked conversation stays attached for live events
        Given a conversation task awaiting the next message over the A2A server
        And a second surface subscribed to it, which replays the log so far
        When the reporter sends the next message and the harness replies
        Then the subscriber receives WORKING and the new reply, live
        When the reporter cancels the task
        Then the subscriber's stream ends with CANCELED, the first terminal state
    """
    tq, context_id = ids()
    server = await make_server(env, [scripted("First."), scripted("Second.")], task_queue=tq)
    async with server:
        tid = await run_to_completion(server, context_id)
        seen: list[StreamResponse] = []

        async def follow() -> None:
            # The in-process transport hands the stream over once it ends, so what the
            # subscriber saw is checked after the task is cancelled.
            async for event in server.a2a().subscribe(SubscribeToTaskRequest(id=tid)):
                seen.append(event)

        watcher = asyncio.create_task(follow())
        await asyncio.sleep(0.3)  # subscribed while the task is parked
        async for _ in server.a2a().send_message(
            SendMessageRequest(message=user_message("more", context_id=context_id, task_id=tid))
        ):
            pass
        await server.a2a().cancel_task(CancelTaskRequest(id=tid))
        await asyncio.wait_for(watcher, timeout=30)
    texts = [
        e.status_update.status.message.parts[0].text
        for e in seen
        if e.HasField("status_update") and e.status_update.status.message.parts
    ]
    assert texts[:1] == ["First."] and "Second." in texts
    states = [e.status_update.status.state for e in seen if e.HasField("status_update")]
    parked = states.index(TaskState.TASK_STATE_INPUT_REQUIRED)
    assert TaskState.TASK_STATE_WORKING in states[parked:]
    last = seen[-1]
    assert last.HasField("status_update")
    assert last.status_update.status.state == TaskState.TASK_STATE_CANCELED
