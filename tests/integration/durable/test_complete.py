"""Feature: Participant completion
Requirement: docs/specs/issue-25/requirements.md#R5

A participant completes a task by sending the control envelope
``{"kind": "control", "action": "complete"}``. The inbox update authorizes it before it
interrupts anything, the workflow runs ``task.complete.in`` with the requester, and the
task finishes ``COMPLETED`` for every subscriber, or the refusal names what is open.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from a2a.types import (
    CancelTaskRequest,
    Message,
    Part,
    SendMessageConfiguration,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    TaskState,
)
from a2a.types import Role as A2ARole
from a2a.utils.errors import A2AError
from google.protobuf import struct_pb2
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import make_server
from tests.integration.a2a.test_server import run_to_completion, user_message
from tests.integration.durable.conftest import (
    Harness,
    close,
    message,
    parked,
    send,
    start,
    task,
    until,
)
from tiny_harness.harness.commands import CommandInvokedIn, CommandResult, CommandSpec, SpawnIntent
from tiny_harness.harness.core import SubState, TaskCompleteIn
from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookPoint, Operation, Phase
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import TaskRecord
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.models import ChildRef
from tiny_harness.service.durable.workflows import TaskWorkflow
from tiny_harness.service.inbox import EVENT_MEDIA_TYPE

pytestmark = pytest.mark.asyncio(loop_scope="module")
GET_ORDER = ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})


def queue() -> str:
    return f"tq-{uuid.uuid4().hex[:8]}"


def task_id() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def control(
    *, task_id: str, message_id: str | None = None, participant: str = "alice", context_id: str = ""
) -> Message:
    """The control envelope any A2A client can send (R5.1)."""
    value = struct_pb2.Value()
    value.struct_value.update({"kind": "control", "action": "complete"})
    msg = Message(
        message_id=message_id or uuid.uuid4().hex,
        task_id=task_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(data=value, media_type=EVENT_MEDIA_TYPE)],
    )
    if context_id:
        msg.context_id = context_id
    msg.metadata.update({"participant_id": participant})
    return msg


def last_state(events: list[StreamResponse]) -> int:
    for event in reversed(events):
        if event.HasField("status_update"):
            return event.status_update.status.state
        if event.HasField("task"):
            return event.task.status.state
    raise AssertionError("no state in the stream")


async def test_a_participant_completes_a_task_and_every_subscriber_sees_completed(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Participant completion
    Requirement: docs/specs/issue-25/requirements.md#R5

    Scenario: A participant completes a task and every subscriber sees COMPLETED
        Given a task working over the A2A server, its turn blocked in a tool call
        And a second surface subscribed to the task
        When the reporter sends the control envelope "complete"
        Then the reporter's stream and the subscriber's both end with COMPLETED
        And the store holds the task COMPLETED, "completed by alice"
    """
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(
        env,
        [scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")],
        task_queue=f"tq-{suffix}",
    )
    server.harness.get_order.gate = asyncio.Event()
    async with server:
        tid = ""
        async for event in server.blocking().send_message(
            SendMessageRequest(
                message=user_message("refund 48213", context_id=f"ctx-{suffix}"),
                configuration=SendMessageConfiguration(return_immediately=True),
            )
        ):
            if event.HasField("task"):
                tid = event.task.id
        assert tid
        await asyncio.wait_for(server.harness.get_order.released.wait(), timeout=30)
        client = server.a2a()

        async def subscribe() -> list[StreamResponse]:
            return [e async for e in client.subscribe(SubscribeToTaskRequest(id=tid))]

        watcher = asyncio.create_task(subscribe())
        await asyncio.sleep(0.2)
        events = [
            e
            async for e in client.send_message(
                SendMessageRequest(message=control(task_id=tid, context_id=f"ctx-{suffix}"))
            )
        ]
        seen = await asyncio.wait_for(watcher, timeout=30)
        final = await env.client.get_workflow_handle(tid).result()
        record = await server.harness.store.get(TaskRecord, tid)
        server.harness.get_order.gate.set()
    assert last_state(events) == TaskState.TASK_STATE_COMPLETED
    assert last_state(seen) == TaskState.TASK_STATE_COMPLETED
    assert final.status.message.parts[0].text == "completed by alice"
    assert record is not None and record.state_name == "COMPLETED"
    assert len(server.harness.llm.requests) == 1


async def test_completing_a_task_interrupts_the_turn_in_progress(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Participant completion
    Requirement: docs/specs/issue-25/requirements.md#R5

    Scenario: Completing a task interrupts the turn in progress
        Given a conversation task whose turn is blocked in a tool call
        When the reporter sends the control envelope "complete"
        Then the turn is cut without another model call
        And the task is COMPLETED, with task.complete.in told who asked
    """
    asked: list[str | None] = []

    async def observe(point: HookPoint, ctx: HookContext) -> HookContext | None:
        if isinstance(ctx, TaskCompleteIn):
            asked.append(ctx.requested_by)
        return None

    h = await Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Refunded.")]).bind()
    h.hooks.register(
        FunctionExecutor(
            "observe",
            observe,
            priority=10,
            points=[HookPoint(operation=Operation.TASK_COMPLETE, phase=Phase.IN)],
        )
    )
    h.get_order.gate = asyncio.Event()
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await asyncio.wait_for(h.get_order.released.wait(), timeout=30)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, control(task_id=tid, message_id="m2")
        )
        result = await handle.result()
        h.get_order.gate.set()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    assert len(h.llm.requests) == 1
    assert asked == ["alice"]


async def test_completing_or_cancelling_a_terminal_task_names_its_state(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Participant completion
    Requirement: docs/specs/issue-25/requirements.md#R5

    Scenario: Completing or cancelling a terminal task names its state
        Given a task the reporter completed
        When the reporter completes it again, or cancels it
        Then each is refused with an error naming TASK_STATE_COMPLETED
        And the task is unchanged
    """
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(env, [scripted("Refunded.")], task_queue=f"tq-{suffix}")
    async with server:
        tid = await run_to_completion(server, f"ctx-{suffix}", "refund 48213")
        client = server.a2a()
        _ = [
            e
            async for e in client.send_message(
                SendMessageRequest(message=control(task_id=tid, context_id=f"ctx-{suffix}"))
            )
        ]
        await env.client.get_workflow_handle(tid).result()
        with pytest.raises(A2AError) as again:
            async for _ in client.send_message(
                SendMessageRequest(message=control(task_id=tid, context_id=f"ctx-{suffix}"))
            ):
                pass
        with pytest.raises(A2AError) as cancel:
            await client.cancel_task(CancelTaskRequest(id=tid))
        record = await server.harness.store.get(TaskRecord, tid)
    assert "TASK_STATE_COMPLETED" in str(again.value)
    assert "TASK_STATE_COMPLETED" in str(cancel.value)
    assert record is not None and record.state_name == "COMPLETED"


async def test_completion_is_refused_while_a_sub_task_is_open(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Participant completion
    Requirement: docs/specs/issue-25/requirements.md#R5

    Scenario: Completion is refused while a sub-task is open
        Given a conversation task with an open conversation sub-task
        When the reporter sends the control envelope "complete"
        Then the reply names the unresolved sub-task
        And the task stays INPUT_REQUIRED awaiting the next message
    """

    def fork(ctx: CommandInvokedIn) -> CommandResult:
        return CommandResult(reply="", spawn=SpawnIntent(goal="look at the ledger"))

    h = await Harness([scripted("Refunded.")]).bind()
    h.commands.register(CommandSpec(name="fork", description="Fork"), fork)
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await until(handle, parked(SubState.AWAITING_NEXT_MESSAGE))
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/fork", task_id=tid, message_id="m2")
        )
        await until(handle, lambda t: bool(t.ext.sub_tasks))
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, control(task_id=tid, message_id="m3")
        )
        refused = await until(
            handle, lambda t: "completion refused" in t.proto.status.message.parts[0].text
        )
        assert f"{tid}.1" in refused.proto.status.message.parts[0].text
        assert parked(SubState.AWAITING_NEXT_MESSAGE)(refused)
        await close(handle)


async def test_a_refused_completion_still_answers_a_message_taken_with_it(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Participant completion (critic A2)
    Requirement: docs/specs/issue-25/requirements.md#R5

    Scenario: a message dispatched together with a refused completion gets its turn
        Given a task with an unresolved sub-task
        And a mailbox holding an ordinary message, then the complete control
        When both are taken in one intake and the completion is refused
        Then the ordinary message still runs a turn and gets its reply
    """
    h = await Harness([scripted("Refunded.")]).bind()
    tq, tid = queue(), task_id()
    open_child = ChildRef(task_id=f"{tid}.1", workflow_id=f"{tid}.1", kind="local")
    first = message("refund 48213", task_id=tid, message_id="m1")
    begin = start(task(tid)).model_copy(
        update={"children": (open_child,), "mailbox": (control(task_id=tid, message_id="m0"),)}
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, begin, first)
        answered = await until(
            handle,
            lambda t: (
                bool(t.proto.status.message.parts)
                and t.proto.status.message.parts[0].text == "Refunded."
            ),
        )
        await close(handle)
    assert parked(SubState.AWAITING_NEXT_MESSAGE)(answered)
    assert len(h.llm.requests) == 1


async def test_a_command_cut_with_its_turn_still_finishes_and_replies(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Commands during a turn (critic A1)
    Requirement: docs/specs/issue-25/requirements.md#R6

    Scenario: an interrupt that cuts the turn does not cut a command it is running
        Given a turn blocked in a tool call, and "/slow" sent meanwhile
        When the turn resumes and "/slow" is running, and an interrupting message arrives
        Then the turn is cut, but "/slow" runs to the end and its reply is logged
    """
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(ctx: CommandInvokedIn) -> CommandResult:
        entered.set()
        await release.wait()
        return CommandResult(reply="slow done")

    h = Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Stopped.")])
    h.commands.register(CommandSpec(name="slow", description="Slow"), slow)
    await h.bind()
    h.get_order.gate = asyncio.Event()
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await asyncio.wait_for(h.get_order.released.wait(), timeout=30)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/slow", task_id=tid, message_id="m2")
        )
        h.get_order.gate.set()
        await asyncio.wait_for(entered.wait(), timeout=30)
        stop = message("stop", task_id=tid, message_id="m3")
        stop.metadata.update({"interrupt": True})
        await handle.execute_update(TaskWorkflow.inbox, stop)  # pyright: ignore[reportUnknownMemberType]
        release.set()
        await until(
            handle,
            lambda t: (
                bool(t.proto.status.message.parts)
                and t.proto.status.message.parts[0].text == "Stopped."
            ),
        )
        page = await handle.query(TaskWorkflow.events_since, 0)
        await close(handle)
    texts = [json.dumps(e.payload) for e in page.events]
    assert any("slow done" in t for t in texts), "the command's reply was lost with the turn"


async def test_a_sub_task_note_survives_a_cut_turn_and_a_rollover(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Participant /sub-task notes the parent (critic A4)
    Requirement: docs/specs/issue-25/requirements.md#R9

    Scenario: the creation note outlives the cut turn and continue-as-new
        Given a turn blocked in a tool call, a small history bound, and "/fork" sent meanwhile
        When "/fork" spawns its sub-task while an interrupting message cuts the turn
        And the workflow rolls over before its next turn
        Then the next model request still carries the creation note
    """
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_fork(ctx: CommandInvokedIn) -> CommandResult:
        entered.set()
        await release.wait()
        return CommandResult(reply="", spawn=SpawnIntent(goal="look at the ledger"))

    h = Harness([scripted("", tool_calls=[GET_ORDER]), scripted("Stopped.")])
    h.commands.register(CommandSpec(name="fork", description="Fork"), slow_fork)
    await h.bind()
    h.get_order.gate = asyncio.Event()
    tq, tid = queue(), task_id()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(task(tid), history_event_bound=30),
            message("refund 48213", task_id=tid, message_id="m1"),
        )
        await asyncio.wait_for(h.get_order.released.wait(), timeout=30)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/fork", task_id=tid, message_id="m2")
        )
        h.get_order.gate.set()
        await asyncio.wait_for(entered.wait(), timeout=30)
        stop = message("stop", task_id=tid, message_id="m3")
        stop.metadata.update({"interrupt": True})
        await handle.execute_update(TaskWorkflow.inbox, stop)  # pyright: ignore[reportUnknownMemberType]
        release.set()
        await until(
            handle,
            lambda t: (
                bool(t.proto.status.message.parts)
                and t.proto.status.message.parts[0].text == "Stopped."
            ),
        )
        await close(handle)
    texts = [getattr(item, "text", "") for item in h.llm.requests[-1].input]
    assert any(f"created sub-task {tid}.1" in t for t in texts), texts
