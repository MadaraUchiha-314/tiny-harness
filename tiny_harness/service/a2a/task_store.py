"""``TaskStore`` over the workflow (R14.1) and the one access policy (abuse case 4):
``get`` queries the task's workflow (or the store once it is purged from Temporal), and
every operation the SDK routes through the store answers the same not-found for a task
the asserted participant is not on. ``save`` is a no-op: the workflow owns the task."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Sequence

from a2a.server.context import ServerCallContext
from a2a.server.tasks import TaskStore
from a2a.types import ListTasksRequest, ListTasksResponse, Task, TaskState
from temporalio.client import Client
from temporalio.service import RPCError

from tiny_harness.harness.core import HarnessTask
from tiny_harness.harness.persistence import Store, TaskRecord

log = logging.getLogger("tiny_harness.a2a.access")
PARTICIPANT_STATE_KEY = "participant_id"
PARTICIPANT_HEADER = "x-participant-id"


def asserted_participant(context: ServerCallContext | None) -> str | None:
    """The self-asserted participant of a request (decision-003): the ``X-Participant-Id``
    header the perimeter may set, read into the call context by the context builder."""
    if context is None:
        return None
    value = context.state.get(PARTICIPANT_STATE_KEY)
    return str(value) if value else None


class AccessPolicy:
    """A task operation needs an asserted participant who is on the task (abuse case 4).

    Fail closed: with no assertion at all the task is as unknown as it is to a stranger.
    The assertion is self-asserted (decision-003); the perimeter is what authenticates it.
    """

    def allows(self, task: Task, context: ServerCallContext | None) -> bool:
        participant = asserted_participant(context)
        if participant is None:
            log.warning("access denied: no participant asserted", extra={"task_id": task.id})
            return False
        try:
            allowed = HarnessTask(task).ext.is_participant(participant)
        except ValueError:
            allowed = False
        if not allowed:
            log.warning("access denied", extra={"task_id": task.id, "participant": participant})
        return allowed


OWNERSHIP_CACHE_SIZE = 4096


def visibility_literal(value: str) -> str:
    """``value`` as a quoted visibility-query string: single quotes doubled, so a request's
    context id cannot end the literal and add a clause (issue-36 design § Security)."""
    return "'" + value.replace("'", "''") + "'"


class TemporalTaskStore(TaskStore):
    """With ``task_queue`` set, a task belongs to this agent only when its workflow runs on
    that queue (issue-36 R5.4, abuse case 2): every other task id is as unknown as one that
    names nothing. The answer never changes for an id, so it is cached. Without it (one
    agent per namespace, the pre-issue-36 setup) every task in the namespace is a candidate."""

    def __init__(
        self,
        client: Client,
        store: Store,
        *,
        policy: AccessPolicy | None = None,
        task_queue: str | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._policy = policy or AccessPolicy()
        self._task_queue = task_queue
        self._owned: OrderedDict[str, bool] = OrderedDict()

    async def save(self, task: Task, context: ServerCallContext) -> None:
        return None

    async def owns(self, task_id: str) -> bool | None:
        """Whether ``task_id``'s workflow runs on this agent's queue; ``None`` when no
        workflow answers (purged, or never existed): only this agent's own store decides."""
        if self._task_queue is None:
            return True
        known = self._owned.get(task_id)
        if known is not None:
            self._owned.move_to_end(task_id)
            return known
        try:
            description = await self._client.get_workflow_handle(task_id).describe()
        except RPCError:
            return None
        owned = description.task_queue == self._task_queue
        self._owned[task_id] = owned
        if len(self._owned) > OWNERSHIP_CACHE_SIZE:
            self._owned.popitem(last=False)
        if not owned:
            log.info("task %s belongs to another agent", task_id)
        return owned

    async def lookup(self, task_id: str) -> Task | None:
        """The task as the workflow sees it, else the store's record, else nothing."""
        owned = await self.owns(task_id)
        if owned is False:
            return None
        if owned:
            handle = self._client.get_workflow_handle(task_id)
            try:
                return await handle.query("task", result_type=Task)
            except RPCError as exc:
                log.info(
                    "task query failed; reading the store",
                    extra={"task_id": task_id, "error": str(exc)},
                )
        record = await self._store.get(TaskRecord, task_id)
        if record is None:
            log.info("task %s not in the store", task_id)
            return None
        return record.task

    async def get(self, task_id: str, context: ServerCallContext) -> Task | None:
        task = await self.lookup(task_id)
        if task is None or not self._policy.allows(task, context):
            return None
        return task

    async def list(self, params: ListTasksRequest, context: ServerCallContext) -> ListTasksResponse:
        query = "WorkflowType = 'TaskWorkflow'"
        if self._task_queue is not None:
            query += f" AND TaskQueue = {visibility_literal(self._task_queue)}"
        if params.context_id:
            query += f" AND A2AContextId = {visibility_literal(params.context_id)}"
        tasks: list[Task] = []
        page_size = params.page_size or 50
        try:
            async for execution in self._client.list_workflows(query):
                if self._task_queue is not None and execution.task_queue != self._task_queue:
                    continue
                task = await self.lookup(execution.id)
                if task is None or not self._policy.allows(task, context):
                    continue
                if params.context_id and task.context_id != params.context_id:
                    continue
                if params.status and task.status.state != params.status:
                    continue
                tasks.append(task)
                if len(tasks) >= page_size:
                    break
        except RPCError as exc:  # visibility without the search attribute: fall back
            log.warning("list_workflows failed", extra={"error": str(exc)})
            tasks = await self._list_from_store(params, context)
        return ListTasksResponse(tasks=tasks, page_size=len(tasks), total_size=len(tasks))

    async def _list_from_store(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> list[Task]:
        from tiny_harness.harness.persistence import Filter

        records: Sequence[TaskRecord] = await self._store.query(
            TaskRecord, Filter(context_id=params.context_id or None)
        )
        found = [r.task for r in records if self._policy.allows(r.task, context)]
        if params.status:
            found = [t for t in found if t.status.state == params.status]
        return found

    async def delete(self, task_id: str, context: ServerCallContext) -> None:
        task = await self.get(task_id, context)
        if task is None:
            return
        await self._store.delete(TaskRecord, task_id)


__all__ = [
    "PARTICIPANT_HEADER",
    "PARTICIPANT_STATE_KEY",
    "AccessPolicy",
    "TaskState",
    "TemporalTaskStore",
    "asserted_participant",
    "visibility_literal",
]
