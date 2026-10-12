"""T10: a task persisted before issue-25 (no ``lifecycle``, ``model``,
``reasoning_effort`` or status key) still loads and answers ``GetTask`` (NFR backwards
compatibility); its lifecycle is derived from ``parent_tasks``."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from a2a.server.context import ServerCallContext
from a2a.types import Task, TaskState, TaskStatus
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from tiny_harness.harness.core import STATUS_EXT_KEY, TASK_EXT_KEY, HarnessTask
from tiny_harness.harness.persistence import SqliteStore, TaskRecord
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.task_store import PARTICIPANT_STATE_KEY, TemporalTaskStore

PRE_CHANGE_EXT: JsonObject = {
    "name": "Audit",
    "type": None,
    "goal": "Audit the ledger",
    "description": "",
    "acceptance_criteria": [],
    "participants": [{"id": "alice", "kind": "human", "role": "reporter", "display_name": ""}],
    "parent_tasks": [],
    "sub_tasks": [],
    "plan": None,
}


def pre_change_task(task_id: str, parent: str | None) -> Task:
    proto = Task(
        id=task_id,
        context_id="ctx-1",
        status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED),
    )
    ext: JsonObject = {**PRE_CHANGE_EXT}
    if parent is not None:
        ext["parent_tasks"] = [{"task_id": parent, "agent": None}]
    proto.metadata.update({TASK_EXT_KEY: ext})
    return proto


class _NoWorkflow:
    """A handle whose query fails, as for a workflow that has finished and been reaped."""

    async def query(self, name: str, *, result_type: type[Task]) -> Task:
        raise RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")


class _Client:
    def get_workflow_handle(self, workflow_id: str) -> _NoWorkflow:
        return _NoWorkflow()


async def test_a_pre_change_task_loads_from_the_store_and_answers_get_task(
    tmp_path: Path,
) -> None:
    store = SqliteStore(tmp_path / "tasks.db")
    for task_id, parent in (("t-1", None), ("t-1.1", "t-1")):
        proto = pre_change_task(task_id, parent)
        await store.put(
            TaskRecord(
                id=task_id,
                context_id="ctx-1",
                task_id=task_id,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                task=proto,
                state_name="INPUT_REQUIRED",
            )
        )
    tasks = TemporalTaskStore(cast(Client, _Client()), store)
    context = ServerCallContext(state={PARTICIPANT_STATE_KEY: "alice"})
    top = await tasks.get("t-1", context)
    child = await tasks.get("t-1.1", context)
    assert top is not None and child is not None
    assert STATUS_EXT_KEY not in top.metadata.fields
    view = HarnessTask(top)
    assert view.ext.lifecycle is None and view.ext.model is None
    assert view.ext.reasoning_effort is None and view.sub_state is None
    assert view.lifecycle == "conversation"
    assert HarnessTask(child).lifecycle == "delegated"
    store.close()
