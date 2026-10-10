"""``HarnessRequestHandler`` (R14.1): the SDK's default handler with ``SubscribeToTask``
served from the durable event log (replayed from sequence 0, across server restarts),
and the access policy applied through the task store on every task operation."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import SubscribeToTaskRequest, Task
from a2a.utils.errors import TaskNotFoundError

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.service.a2a.bridge import EventBridge


class HarnessRequestHandler(DefaultRequestHandler):
    def __init__(self, *, bridge: EventBridge, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._bridge = bridge

    async def on_subscribe_to_task(  # type: ignore[override]
        self, params: SubscribeToTaskRequest, context: ServerCallContext | None = None
    ) -> AsyncGenerator[A2AEvent]:
        task: Task | None = await self.task_store.get(params.id, context)  # type: ignore[arg-type]
        if task is None:
            raise TaskNotFoundError
        yield task
        async for event in self._bridge.events(params.id, 1):
            yield event


__all__ = ["HarnessRequestHandler"]
