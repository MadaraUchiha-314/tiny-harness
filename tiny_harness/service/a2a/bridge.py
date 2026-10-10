"""The event bridge (R14.5, decision-002): how the workflow's durable event log reaches a
streaming request. ``PollingEventBridge`` queries ``events_since`` every interval; a
multi-process deployment replaces it with the SDK's own event stream seam."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Protocol

from a2a.types import Message, Task, TaskState, TaskStatusUpdateEvent
from temporalio.client import Client
from temporalio.service import RPCError

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.service.durable.models import EventPage, entry_event

FINAL_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_REJECTED,
        TaskState.TASK_STATE_INPUT_REQUIRED,
        TaskState.TASK_STATE_AUTH_REQUIRED,
    }
)


def is_final(event: A2AEvent) -> bool:
    """The SDK's own rule: a Message, or a Task/status update in a final or waiting state."""
    if isinstance(event, Message):
        return True
    if isinstance(event, (Task, TaskStatusUpdateEvent)):
        return event.status.state in FINAL_STATES
    return False


class EventBridge(Protocol):
    def events(self, task_id: str, cursor: int) -> AsyncIterator[A2AEvent]: ...

    async def page(self, task_id: str, cursor: int) -> EventPage | None: ...


class PollingEventBridge:
    def __init__(
        self, client: Client, *, interval: timedelta = timedelta(milliseconds=250)
    ) -> None:
        self._client = client
        self._interval = interval.total_seconds()

    async def page(self, task_id: str, cursor: int) -> EventPage | None:
        handle = self._client.get_workflow_handle(task_id)
        try:
            return await handle.query("events_since", cursor, result_type=EventPage)
        except RPCError:
            return None

    async def events(self, task_id: str, cursor: int) -> AsyncIterator[A2AEvent]:
        """Yield from ``cursor`` until a final event, the log closing, or the task vanishing.

        A final event ends the stream only when it is the newest event in the log: a
        replay (``SubscribeToTask`` from the start) runs past an earlier ``INPUT_REQUIRED``
        the task has since left, so a second surface sees the whole task (R20.3).
        """
        while True:
            page = await self.page(task_id, cursor)
            if page is None:
                return
            for entry in page.events:
                event = entry_event(entry)
                cursor = entry.seq + 1
                yield event
                if is_final(event) and cursor >= page.next_seq:
                    return
            if page.closed:
                return
            await asyncio.sleep(self._interval)


__all__ = ["FINAL_STATES", "EventBridge", "PollingEventBridge", "is_final"]
