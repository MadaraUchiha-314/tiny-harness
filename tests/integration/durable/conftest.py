"""The Temporal time-skipping test environment and a worker over fakes (T2)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import timedelta
from pathlib import Path

import pytest_asyncio
from a2a.types import Message, Part, Task
from a2a.types import Role as A2ARole
from temporalio.client import Client, WithStartWorkflowOperation, WorkflowHandle
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from tiny_harness.harness.core import (
    AgentState,
    ContextWindowManager,
    HarnessTask,
    Participant,
    Role,
    TaskExtensionData,
)
from tiny_harness.harness.core.inprocess import InProcessOperations
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.models import FakeLLM, LLMResponse
from tiny_harness.harness.persistence import SqliteStore
from tiny_harness.harness.tools import (
    Idempotency,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolResult,
    WorkflowCommand,
)
from tiny_harness.service.durable.activities import Activities, EventSink
from tiny_harness.service.durable.models import TaskStart, WorkflowConfig
from tiny_harness.service.durable.worker import build_worker
from tiny_harness.service.durable.workflows import TaskWorkflow

CACHE = Path.home() / ".cache" / "temporalio"


class FakeTool(Tool):
    """A tool whose body the test controls: it may block, fail N times, or record."""

    def __init__(self, name: str, *, idempotency: Idempotency) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.TOOL, id=name, version=None),
            ToolDefinition(
                name=name,
                description="fake",
                input_schema={"type": "object"},
                idempotency=idempotency,
            ),
        )
        self.calls: list[ToolCall] = []
        self.fail_times = 0
        self.gate: asyncio.Event | None = None
        self.released = asyncio.Event()

    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand:
        self.calls.append(call)
        if self.gate is not None:
            self.released.set()
            await self.gate.wait()
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("transient failure")
        return ToolResult.text(call.call_id, f"ok {len(self.calls)}")


class Harness:
    """Everything one worker needs, over fakes."""

    def __init__(
        self, responses: Sequence[LLMResponse], *, turn_budget_tokens: int = 12_000
    ) -> None:
        self.registry = Registry()
        self.hooks = HookManager()
        self.llm = FakeLLM(list(responses))
        self.store = SqliteStore(":memory:")
        self.get_order = FakeTool("orders.get_order", idempotency=Idempotency.IDEMPOTENT)
        self.refund = FakeTool("orders.refund", idempotency=Idempotency.NOT_IDEMPOTENT)
        self.heartbeat_every = 10.0
        self.activities: Activities | None = None
        self.engine = InProcessOperations(
            registry=self.registry,
            hooks=self.hooks,
            llm=self.llm,
            store=self.store,
            system_prompt="You are the harness.",
            manager=ContextWindowManager(turn_budget_tokens=turn_budget_tokens),
        )

    async def bind(self) -> Harness:
        await self.engine.bind()
        for tool in (self.get_order, self.refund):
            await self.registry.add(RegistryEntry(ref=tool.ref, instance=tool))
        return self

    def worker(self, client: Client, task_queue: str, *, sink: EventSink | None = None) -> Worker:
        self.activities = Activities(self.engine, sink=sink, client=client)
        self.activities.heartbeat_every = self.heartbeat_every
        return build_worker(client, self.activities, task_queue=task_queue)


def task(task_id: str = "t-1", context_id: str = "ctx-1") -> HarnessTask:
    return HarnessTask.new(
        task_id,
        context_id,
        TaskExtensionData(
            name="Refund",
            goal="Resolve the complaint",
            participants=(
                Participant(id="alice", kind="human", role=Role.REPORTER),
                Participant(id="agent", kind="agent", role=Role.ASSIGNEE),
            ),
        ),
    )


def start(
    t: HarnessTask | None = None,
    *,
    history_event_bound: int = 10_000,
    max_turns: int = 20,
    heartbeat_timeout: timedelta = timedelta(seconds=30),
) -> TaskStart:
    t = t or task()
    return TaskStart(
        task=t.proto,
        state=AgentState(task_id=t.id),
        config=WorkflowConfig(
            history_event_bound=history_event_bound,
            max_turns=max_turns,
            search_attributes=False,
            heartbeat_timeout=heartbeat_timeout,
        ),
        correlation_id="test",
    )


def message(
    text: str,
    *,
    task_id: str = "t-1",
    context_id: str = "ctx-1",
    message_id: str,
    participant: str | None = "alice",
) -> Message:
    msg = Message(
        message_id=message_id,
        context_id=context_id,
        task_id=task_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(text=text)],
    )
    if participant is not None:
        msg.metadata.update({"participant_id": participant})
    return msg


async def send(
    client: Client, task_queue: str, start_arg: TaskStart, msg: Message
) -> WorkflowHandle[TaskWorkflow, Task]:
    """``SendMessage`` as the executor does it: update-with-start on the task's workflow."""
    operation: WithStartWorkflowOperation[TaskWorkflow, Task] = WithStartWorkflowOperation(
        TaskWorkflow.run,
        start_arg,
        id=start_arg.task.id,
        task_queue=task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    receipt = await client.execute_update_with_start_workflow(  # pyright: ignore[reportUnknownMemberType]
        TaskWorkflow.inbox, msg, start_workflow_operation=operation
    )
    assert receipt.accepted
    return await operation.workflow_handle()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env() -> AsyncIterator[WorkflowEnvironment]:
    CACHE.mkdir(parents=True, exist_ok=True)  # the server binary is cached across runs
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter, download_dest_dir=str(CACHE)
    ) as environment:
        yield environment


HarnessFactory = Callable[[Sequence[LLMResponse]], Harness]

__all__ = [
    "CACHE",
    "FakeTool",
    "Harness",
    "HarnessFactory",
    "env",
    "message",
    "send",
    "start",
    "task",
]
