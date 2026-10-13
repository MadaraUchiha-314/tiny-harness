"""Two in-process harnesses for issue-27: a local one that delegates to a remote one.

The remote server's outbound pushes go to the local app over ``httpx.ASGITransport``, so a
push travels the real route: the SDK's sender, ``LimitsMiddleware``, the endpoint and the
``remote_push`` update."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from a2a.types import Message, Part, Task, TaskState
from a2a.types import Role as A2ARole
from google.protobuf import struct_pb2
from starlette.applications import Starlette
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import Server, make_server
from tests.integration.durable.conftest import message, send, start, task
from tests.integration.streaming_asgi import StreamingASGITransport
from tiny_harness.harness.agents import RemoteAgent
from tiny_harness.harness.agents.remote import UpdateMode
from tiny_harness.harness.entities import RegistryEntry
from tiny_harness.harness.models import LLMResponse, scripted
from tiny_harness.harness.persistence import Filter, PushConfigRecord, TaskRecord
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.models import InboxReceipt
from tiny_harness.service.durable.workflows import TaskWorkflow
from tiny_harness.service.inbox import EVENT_MEDIA_TYPE

LOCAL_BASE = "http://local"


def delegate(agent: str = "ledger") -> ToolCall:
    return ToolCall(
        call_id="c1",
        name="spawn_subtask",
        arguments={"name": "Ledger check", "goal": "Check the ledger for 48213", "agent": agent},
    )


def ask(question: str = "Which ledger?") -> ToolCall:
    """The remote parks its task awaiting an answer from this harness, its reporter."""
    return ToolCall(
        call_id="r1",
        name="ask_participant",
        arguments={"participant_id": "tiny-harness", "question": question},
    )


def control_complete(task_id: str, participant: str = "tiny-harness") -> Message:
    value = struct_pb2.Value()
    value.struct_value.update({"kind": "control", "action": "complete"})
    msg = Message(
        message_id=uuid.uuid4().hex,
        task_id=task_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(data=value, media_type=EVENT_MEDIA_TYPE)],
    )
    msg.metadata.update({"participant_id": participant})
    return msg


def parent_script() -> list[LLMResponse]:
    """Spare replies at the end: how many turns the parent takes depends on when it hears
    each of its child's changes, which a test does not fix."""
    return [
        scripted("", tool_calls=[delegate()]),
        scripted("Waiting on the ledger."),
        scripted("Noted."),
        scripted("Noted again."),
        *(scripted("Still noted.") for _ in range(4)),
    ]


@dataclass
class Delegation:
    env: WorkflowEnvironment
    local: Server
    remote: Server
    agent: RemoteAgent
    queue: str
    task_id: str

    @property
    def child_id(self) -> str:
        return f"{self.task_id}.1"

    async def begin(
        self, *, history_event_bound: int = 10_000
    ) -> WorkflowHandle[TaskWorkflow, Task]:
        return await send(
            self.env.client,
            self.queue,
            start(
                task(self.task_id, f"ctx-{self.task_id}"), history_event_bound=history_event_bound
            ),
            message(
                "refund 48213",
                task_id=self.task_id,
                context_id=f"ctx-{self.task_id}",
                message_id=f"{self.task_id}:m1",
            ),
        )

    async def remote_id(self) -> str:
        """The child's own task on the remote agent, which the parent's row and notes name
        (issue-34 R7.4); ``child_id`` is the stand-in that follows it."""
        for _ in range(400):
            if records := await self.remote.harness.store.query(TaskRecord, Filter()):
                return records[0].task_id
            await asyncio.sleep(0.05)
        raise AssertionError("the remote never created the child's task")

    async def parked_remote(self) -> str:
        """The remote task id once the remote has parked it awaiting an answer."""
        for _ in range(400):
            for record in await self.remote.harness.store.query(TaskRecord, Filter()):
                if record.state_name == "INPUT_REQUIRED":
                    return record.task_id
            await asyncio.sleep(0.05)
        raise AssertionError("the remote never parked its task")

    async def quiet_pushes(self, *, quiet: float = 2.0) -> None:
        """Until the remote has sent no push for ``quiet`` seconds. A tiny-harness remote
        can push the same status twice, the second a few seconds after the first (both
        doorbells, harmless); a test measuring a window waits for it to pass."""
        seen = -1
        for _ in range(100):
            if len(self.remote.pushes) == seen:
                return
            seen = len(self.remote.pushes)
            await asyncio.sleep(quiet)
        raise AssertionError("the remote never stopped pushing")

    async def push_configs(self, remote_id: str) -> list[PushConfigRecord]:
        return list(
            await self.remote.harness.store.query(PushConfigRecord, Filter(task_id=remote_id))
        )

    async def until_push_config(self, remote_id: str) -> PushConfigRecord:
        for _ in range(400):
            if configs := await self.push_configs(remote_id):
                return configs[0]
            await asyncio.sleep(0.05)
        raise AssertionError("the stand-in never registered a push config")

    async def cancel_remote(self, remote_id: str, reason: str = "stopped by the operator") -> None:
        """A third party ends the remote task on the remote side."""
        await self.env.client.get_workflow_handle(remote_id).signal("cancel", reason)

    async def complete_remote(self, remote_id: str) -> None:
        handle = self.env.client.get_workflow_handle(remote_id)
        receipt = await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            "inbox", control_complete(remote_id), result_type=InboxReceipt
        )
        assert receipt.accepted

    async def events(self, event_type: str, activity: str | None = None) -> int:
        """How many ``EVENT_TYPE_<event_type>`` events the stand-in's current run holds,
        only for ``activity`` when given (a scheduled activity's name)."""
        handle = self.env.client.get_workflow_handle(self.child_id)
        count = 0
        async for e in handle.fetch_history_events():
            if EventType.Name(e.event_type) != f"EVENT_TYPE_{event_type}":
                continue
            if activity is not None and (
                e.activity_task_scheduled_event_attributes.activity_type.name != activity
            ):
                continue
            count += 1
        return count

    async def continued(self) -> bool:
        """Whether the stand-in's current run was continued as new from an earlier one."""
        handle = self.env.client.get_workflow_handle(self.child_id)
        async for e in handle.fetch_history_events():
            return bool(e.workflow_execution_started_event_attributes.continued_execution_run_id)
        return False

    async def child(self) -> Task:
        return await self.env.client.get_workflow_handle(self.child_id).result()

    async def child_state(self) -> int:
        handle = self.env.client.get_workflow_handle(self.child_id)
        current = await handle.query("task", result_type=Task)
        return current.status.state

    async def until_child(self, state: int) -> None:
        for _ in range(400):
            if await self.child_state() == state:
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"the stand-in never reached {TaskState.Name(state)}")


@asynccontextmanager
async def delegation(
    env: WorkflowEnvironment,
    parent: Sequence[LLMResponse],
    remote: Sequence[LLMResponse],
    *,
    updates: UpdateMode = "auto",
    configure: Callable[[RemoteAgent], None] | None = None,
) -> AsyncGenerator[Delegation]:
    suffix = uuid.uuid4().hex[:8]
    apps: dict[str, Starlette] = {}

    async def to_local(request: httpx.Request) -> httpx.Response:
        response = await httpx.ASGITransport(app=apps["local"]).handle_async_request(request)
        await response.aread()
        return response

    remote_server = await make_server(env, remote, task_queue=f"tq-r-{suffix}", push_to=to_local)
    local_server = await make_server(
        env, parent, task_queue=f"tq-l-{suffix}", push_base_url=LOCAL_BASE
    )
    apps["local"] = local_server.app
    async with remote_server, local_server:
        http = httpx.AsyncClient(
            transport=StreamingASGITransport(remote_server.app), base_url="http://harness"
        )
        agent = await RemoteAgent.connect("ledger", "http://harness", http=http, updates=updates)
        if configure is not None:
            configure(agent)
        await local_server.harness.registry.add(RegistryEntry(ref=agent.ref, instance=agent))
        try:
            yield Delegation(
                env=env,
                local=local_server,
                remote=remote_server,
                agent=agent,
                queue=f"tq-l-{suffix}",
                task_id=f"t-{suffix}",
            )
        finally:
            await agent.close()
