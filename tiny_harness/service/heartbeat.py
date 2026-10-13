"""The heartbeat (R16): a Temporal schedule starts ``HeartbeatWorkflow`` every interval.
A schedule rather than a process loop because it survives the server process and is
visible in Temporal (R16.5)."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from tiny_harness.config import DEFAULT_AGENT_ID
from tiny_harness.service.durable.models import HeartbeatTick

SCHEDULE_ID: Final = "tiny-harness-heartbeat"


def schedule_id(agent_id: str = DEFAULT_AGENT_ID) -> str:
    """One schedule per agent (issue-36 R5.6); the default agent keeps the name it always
    had, so an existing deployment keeps its schedule (R7)."""
    return SCHEDULE_ID if agent_id == DEFAULT_AGENT_ID else f"{SCHEDULE_ID}-{agent_id}"


async def ensure_heartbeat_schedule(
    client: Client, *, interval: timedelta, task_queue: str, agent_id: str = DEFAULT_AGENT_ID
) -> bool:
    """Create the agent's schedule; ``False`` when it already exists (the worker is
    restarting)."""
    name = schedule_id(agent_id)
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "HeartbeatWorkflow",
            HeartbeatTick(task_queue=task_queue),
            id=f"{name}-run",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    try:
        await client.create_schedule(name, schedule)
    except ScheduleAlreadyRunningError:
        return False
    return True


async def delete_heartbeat_schedule(client: Client, agent_id: str = DEFAULT_AGENT_ID) -> None:
    await client.get_schedule_handle(schedule_id(agent_id)).delete()


__all__ = ["SCHEDULE_ID", "delete_heartbeat_schedule", "ensure_heartbeat_schedule", "schedule_id"]
