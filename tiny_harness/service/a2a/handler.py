"""``HarnessRequestHandler`` (R14.1): the SDK's default handler with ``SubscribeToTask``
served from the durable event log (replayed from sequence 0, across server restarts),
and the access policy applied through the task store on every task operation."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import cast

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.types import CancelTaskRequest, Message, SendMessageRequest, SubscribeToTaskRequest, Task
from a2a.utils.errors import TaskNotFoundError

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.service.a2a.bridge import EventBridge
from tiny_harness.service.a2a.executor import HarnessExecutor, refuse_terminal, refuse_watcher
from tiny_harness.service.a2a.task_store import asserted_participant
from tiny_harness.service.inbox import is_control


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

    async def _refuse_terminal_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Task | None:
        """The SDK refuses a message to a task its process saw finish with "already
        completed"; checked here first, the refusal names the state (issue-25 R5.3). A
        stranger's lookup is ``None`` and falls through to the SDK's not-found."""
        task_id = params.message.task_id
        if not task_id:
            return None
        task: Task | None = await self.task_store.get(task_id, context)  # type: ignore[arg-type]
        if task is not None:
            refuse_terminal(task)
        return task

    def _control(
        self, task: Task | None, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[A2AEvent] | None:
        """A control envelope bypasses the SDK's per-task queue (``HarnessExecutor.control``)."""
        if not is_control(params.message) or not params.message.task_id:
            return None
        if task is None:
            raise TaskNotFoundError
        executor = self.agent_executor
        assert isinstance(executor, HarnessExecutor)
        return executor.control(task, params.message, context)

    async def on_message_send(  # type: ignore[override]
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Message | Task:
        task = await self._refuse_terminal_send(params, context)
        control = self._control(task, params, context)
        if control is not None:
            async for _ in control:
                pass
            final: Task | None = await self.task_store.get(params.message.task_id, context)  # type: ignore[arg-type]
            if final is None:
                raise TaskNotFoundError
            return final
        send = super().on_message_send  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return cast(Message | Task, await send(params, context))

    async def on_message_send_stream(  # type: ignore[override]
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[A2AEvent]:
        task = await self._refuse_terminal_send(params, context)
        control = self._control(task, params, context)
        if control is not None:
            async for event in control:
                yield event
            return
        stream = super().on_message_send_stream  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        events = cast(AsyncGenerator[A2AEvent], stream(params, context))
        async for event in events:
            yield event

    async def on_cancel_task(  # type: ignore[override]
        self, params: CancelTaskRequest, context: ServerCallContext
    ) -> Task | None:
        """The SDK answers a terminal task, or an executor refusal, with a bare
        "cannot be canceled"; checked here first, the refusal names the state or the role
        (issue-25 R5.3, abuse case 4)."""
        task: Task | None = await self.task_store.get(params.id, context)  # type: ignore[arg-type]
        if task is None:
            raise TaskNotFoundError
        refuse_terminal(task)
        refuse_watcher(task, asserted_participant(context))
        cancel = super().on_cancel_task  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return cast(Task | None, await cancel(params, context))


__all__ = ["HarnessRequestHandler"]
