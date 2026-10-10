"""Feature: A2A server
Requirement: docs/specs/issue-3/requirements.md#R14, #R20 (R20.3)

The event bridge ends a stream at a final event only when that event is the newest one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import cast

from a2a.types import Task, TaskState, TaskStatus, TaskStatusUpdateEvent
from temporalio.client import Client

from tiny_harness.service.a2a.bridge import PollingEventBridge
from tiny_harness.service.durable.models import EventEntry, EventPage, event_entry


class LogBridge(PollingEventBridge):
    """The bridge over a canned event log instead of a workflow query."""

    def __init__(self, entries: list[EventEntry]) -> None:
        super().__init__(cast(Client, object()), interval=timedelta(milliseconds=1))
        self.entries = entries

    async def page(self, task_id: str, cursor: int) -> EventPage | None:
        return EventPage(
            events=tuple(e for e in self.entries if e.seq >= cursor),
            next_seq=len(self.entries) + 1,
            closed=False,
        )


def status(seq: int, state: TaskState) -> EventEntry:
    return event_entry(
        seq, TaskStatusUpdateEvent(task_id="t1", context_id="c1", status=TaskStatus(state=state))
    )


def log(*states: TaskState) -> list[EventEntry]:
    first = event_entry(
        1, Task(id="t1", context_id="c1", status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
    )
    return [first, *(status(i + 2, s) for i, s in enumerate(states))]


async def states_from(bridge: LogBridge, cursor: int) -> list[TaskState]:
    out: list[TaskState] = []
    async for event in bridge.events("t1", cursor):
        assert isinstance(event, (Task, TaskStatusUpdateEvent))
        out.append(event.status.state)
    return out


async def test_a_replay_runs_past_an_earlier_final_event_to_the_newest_one() -> None:
    """
    Scenario: a replay runs past an earlier final event to the newest one
        Given a log where the task waited in INPUT_REQUIRED, then worked and completed
        When a subscriber replays from the start
        Then it receives every event up to COMPLETED, not only up to the first wait
    """
    bridge = LogBridge(
        log(
            TaskState.TASK_STATE_WORKING,
            TaskState.TASK_STATE_INPUT_REQUIRED,
            TaskState.TASK_STATE_WORKING,
            TaskState.TASK_STATE_COMPLETED,
        )
    )
    assert await states_from(bridge, 1) == [
        TaskState.TASK_STATE_SUBMITTED,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_INPUT_REQUIRED,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_COMPLETED,
    ]


async def test_a_stream_still_ends_at_the_newest_final_event() -> None:
    """
    Scenario: a stream still ends at the newest final event
        Given a log whose newest event is INPUT_REQUIRED
        When a stream reads from the start
        Then it ends at that event instead of polling forever
    """
    bridge = LogBridge(log(TaskState.TASK_STATE_WORKING, TaskState.TASK_STATE_INPUT_REQUIRED))
    assert await states_from(bridge, 1) == [
        TaskState.TASK_STATE_SUBMITTED,
        TaskState.TASK_STATE_WORKING,
        TaskState.TASK_STATE_INPUT_REQUIRED,
    ]
