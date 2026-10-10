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

from tiny_harness.service.durable.models import HeartbeatTick

SCHEDULE_ID: Final = "tiny-harness-heartbeat"


async def ensure_heartbeat_schedule(
    client: Client, *, interval: timedelta, task_queue: str
) -> bool:
    """Create the schedule; ``False`` when it already exists (the worker is restarting)."""
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            "HeartbeatWorkflow",
            HeartbeatTick(task_queue=task_queue),
            id=f"{SCHEDULE_ID}-run",
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    try:
        await client.create_schedule(SCHEDULE_ID, schedule)
    except ScheduleAlreadyRunningError:
        return False
    return True


async def delete_heartbeat_schedule(client: Client) -> None:
    await client.get_schedule_handle(SCHEDULE_ID).delete()


__all__ = ["SCHEDULE_ID", "delete_heartbeat_schedule", "ensure_heartbeat_schedule"]
