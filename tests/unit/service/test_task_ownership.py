"""Task ownership by queue (issue-36 R5.4, R5.6, abuse case 2): with a task queue set, the
task store treats a task whose workflow runs on another queue as unknown; a failed
``describe`` falls back to this agent's own store only; a known id is never described
twice; and the visibility queries quote what they interpolate."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from a2a.server.context import ServerCallContext
from a2a.types import ListTasksRequest, Task
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.harness.persistence import SqliteStore, TaskRecord
from tiny_harness.service.a2a.task_store import (
    PARTICIPANT_STATE_KEY,
    TemporalTaskStore,
    visibility_literal,
)
from tiny_harness.service.durable.activities import running_task_workflows

ALICE = ServerCallContext(state={PARTICIPANT_STATE_KEY: "alice"})


def a_task(task_id: str) -> Task:
    ext = TaskExtensionData(
        name="t",
        goal="g",
        participants=(Participant(id="alice", kind="human", role=Role.REPORTER),),
    )
    return HarnessTask.new(task_id, "ctx", ext).proto


@dataclass
class Description:
    task_queue: str


@dataclass
class Execution:
    id: str
    task_queue: str
    workflow_type: str = "TaskWorkflow"


@dataclass
class FakeClient:
    queues: dict[str, str]  # workflow id -> its queue
    describes: list[str] = field(default_factory=lambda: list[str]())
    queries: list[str] = field(default_factory=lambda: list[str]())
    listed: list[str] = field(default_factory=lambda: list[str]())

    def get_workflow_handle(self, workflow_id: str) -> Handle:
        return Handle(self, workflow_id)

    def list_workflows(self, query: str | None = None) -> AsyncIterator[Execution]:
        self.listed.append(query or "")

        async def executions() -> AsyncIterator[Execution]:
            for workflow_id, queue in self.queues.items():
                yield Execution(workflow_id, queue)

        return executions()


@dataclass
class Handle:
    client: FakeClient
    workflow_id: str

    async def describe(self) -> Description:
        self.client.describes.append(self.workflow_id)
        queue = self.client.queues.get(self.workflow_id)
        if queue is None:
            raise RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
        return Description(queue)

    async def query(self, name: str, *, result_type: type[Task]) -> Task:
        self.client.queries.append(self.workflow_id)
        return a_task(self.workflow_id)


def store_for(fake: FakeClient, queue: str | None = "a") -> TemporalTaskStore:
    return TemporalTaskStore(cast(Client, fake), SqliteStore(":memory:"), task_queue=queue)


async def test_an_owned_task_is_answered() -> None:
    fake = FakeClient({"t1": "a"})
    task = await store_for(fake).get("t1", ALICE)
    assert task is not None and task.id == "t1"


async def test_another_agents_task_is_unknown_and_never_queried() -> None:
    fake = FakeClient({"t1": "b"})
    assert await store_for(fake).get("t1", ALICE) is None
    assert fake.queries == []


async def test_a_known_id_is_described_once() -> None:
    fake = FakeClient({"t1": "a", "t2": "b"})
    tasks = store_for(fake)
    for _ in range(3):
        await tasks.get("t1", ALICE)
        await tasks.get("t2", ALICE)
    assert sorted(fake.describes) == ["t1", "t2"]


async def test_no_workflow_falls_back_to_this_agents_own_store() -> None:
    fake = FakeClient({})
    tasks = store_for(fake)
    await tasks._store.put(  # pyright: ignore[reportPrivateUsage]
        TaskRecord(
            id="old",
            context_id="ctx",
            task_id="old",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            task=a_task("old"),
            state_name="COMPLETED",
        )
    )
    found = await tasks.get("old", ALICE)
    assert found is not None and found.id == "old"
    assert await tasks.get("never", ALICE) is None
    assert fake.queries == []


async def test_without_a_queue_every_task_is_a_candidate() -> None:
    fake = FakeClient({"t1": "anything"})
    assert await store_for(fake, queue=None).get("t1", ALICE) is not None
    assert fake.describes == []


async def test_list_tasks_filters_by_queue_and_quotes_the_context() -> None:
    fake = FakeClient({"t1": "a", "t2": "b"})
    response = await store_for(fake).list(ListTasksRequest(context_id="x' OR 'y"), ALICE)
    assert fake.listed == [
        "WorkflowType = 'TaskWorkflow' AND TaskQueue = 'a' AND A2AContextId = 'x'' OR ''y'"
    ]
    assert [t.id for t in response.tasks] == []  # t1's context is "ctx", not the request's


async def test_list_tasks_skips_another_agents_executions() -> None:
    fake = FakeClient({"t1": "a", "t2": "b"})
    response = await store_for(fake).list(ListTasksRequest(), ALICE)
    assert [t.id for t in response.tasks] == ["t1"]


async def test_the_heartbeat_scan_is_scoped_to_the_queue() -> None:
    fake = FakeClient({"t1": "a", "t2": "b"})
    assert await running_task_workflows(cast(Client, fake), "a") == ["t1"]
    assert "TaskQueue = 'a'" in fake.listed[0]


def test_visibility_literal_doubles_quotes() -> None:
    assert visibility_literal("it's") == "'it''s'"
