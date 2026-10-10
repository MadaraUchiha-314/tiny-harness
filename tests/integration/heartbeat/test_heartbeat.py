"""Feature: Heartbeat
Requirement: docs/specs/issue-3/requirements.md#R16

A Temporal schedule ticks the harness: pull channels are drained, the inner layer snapshotted.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from a2a.types import TaskState
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from tests.integration.durable.conftest import CACHE, Harness, message, send, start
from tiny_harness.harness.channels import Channel, ChannelMessage
from tiny_harness.harness.entities import EntityKind, EntityRef, RegistryEntry
from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookPoint, Operation, Phase
from tiny_harness.harness.models import scripted
from tiny_harness.harness.tools import ContentPart, ToolCall
from tiny_harness.service.durable.models import HeartbeatTick, HeartbeatTickPre
from tiny_harness.service.durable.workflows import HeartbeatWorkflow, TaskWorkflow
from tiny_harness.service.heartbeat import (
    SCHEDULE_ID,
    delete_heartbeat_schedule,
    ensure_heartbeat_schedule,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


class PullChannel(Channel):
    """A channel the harness must poll: messages wait in a queue until a tick."""

    pull = True

    def __init__(self, task_id: str, members: list[str]) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.CHANNEL, id=f"pull:{task_id}", version=None),
            task_id=task_id,
            members=members,
        )
        self.queue: list[ChannelMessage] = []
        self.sent: list[ChannelMessage] = []

    async def send(self, message: ChannelMessage) -> None:
        self.sent.append(message)

    async def receive(self) -> AsyncIterator[ChannelMessage]:
        while self.queue:
            yield self.queue.pop(0)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def local_env() -> AsyncIterator[WorkflowEnvironment]:
    CACHE.mkdir(parents=True, exist_ok=True)
    async with await WorkflowEnvironment.start_local(  # pyright: ignore[reportUnknownMemberType]
        data_converter=pydantic_data_converter, download_dest_dir=str(CACHE)
    ) as environment:
        yield environment


async def test_a_schedule_tick_forwards_a_pull_channel_message_to_its_task(
    local_env: WorkflowEnvironment,
) -> None:
    """
    Feature: Heartbeat
    Requirement: docs/specs/issue-3/requirements.md#R16

    Scenario: a schedule tick forwards a pull-channel message to its task
        Given a task waiting in INPUT_REQUIRED for alice's reply, on the dev server
        And alice's reply waits on a pull channel
        When the heartbeat workflow runs one tick
        Then the reply reaches the task's inbox and the task completes
        And the tick's snapshot, listing the task, reached the heartbeat.tick hook
    """
    ask = ToolCall(
        call_id="c1",
        name="ask_participant",
        arguments={"participant_id": "alice", "question": "Full or partial?"},
    )
    h = await Harness([scripted("", tool_calls=[ask]), scripted("Full refund issued.")]).bind()
    channel = PullChannel("t-1", ["alice", "agent"])
    await h.registry.add(RegistryEntry(ref=channel.ref, instance=channel))
    snapshots: list[HeartbeatTickPre] = []

    async def observe(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, HeartbeatTickPre)
        snapshots.append(ctx)
        return None

    h.hooks.register(
        FunctionExecutor(
            "observe",
            observe,
            points=[HookPoint(operation=Operation.HEARTBEAT_TICK, phase=Phase.PRE)],
        )
    )
    tq = f"tq-{uuid.uuid4().hex[:8]}"
    async with h.worker(local_env.client, tq):
        handle = await send(local_env.client, tq, start(), message("refund 48213", message_id="m1"))
        for _ in range(100):
            current = await handle.query(TaskWorkflow.task_query)
            if current.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
                break
            await asyncio.sleep(0.1)
        channel.queue.append(
            ChannelMessage(
                id="reply-1",
                channel_id=channel.id,
                sender="alice",
                parts=(ContentPart(kind="text", text="Full."),),
                at=datetime.now(UTC),
                kind="help_reply",
            )
        )
        result = await local_env.client.execute_workflow(
            HeartbeatWorkflow.run,
            HeartbeatTick(task_queue=tq),
            id=f"heartbeat-{uuid.uuid4().hex[:8]}",
            task_queue=tq,
        )
        assert result.forwarded == 1
        final = await handle.result()
    assert final.status.state == TaskState.TASK_STATE_COMPLETED
    assert snapshots and snapshots[0].snapshot.tasks
    seen = [t for t in snapshots[0].snapshot.tasks if t.task_id == "t-1"]
    assert seen, "the snapshot lists the running task"
    # The poll ran first in the same tick, so the task had already left INPUT_REQUIRED.
    assert seen[0].state_name in {"WORKING", "COMPLETED"}


async def test_the_heartbeat_schedule_is_created_once_and_can_be_deleted(
    local_env: WorkflowEnvironment,
) -> None:
    """
    Feature: Heartbeat
    Requirement: docs/specs/issue-3/requirements.md#R16

    Scenario: the heartbeat is a Temporal schedule
        When the worker ensures the schedule twice
        Then it exists once with the configured interval
        And `schedules delete` removes it
    """
    client = local_env.client
    assert await ensure_heartbeat_schedule(client, interval=timedelta(seconds=30), task_queue="tq")
    assert not await ensure_heartbeat_schedule(
        client, interval=timedelta(seconds=30), task_queue="tq"
    )
    description = await client.get_schedule_handle(SCHEDULE_ID).describe()
    assert description.schedule.spec.intervals[0].every == timedelta(seconds=30)
    await delete_heartbeat_schedule(client)
    assert await ensure_heartbeat_schedule(client, interval=timedelta(seconds=5), task_queue="tq")
    await delete_heartbeat_schedule(client)
