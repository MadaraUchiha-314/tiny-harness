"""The A2A executor (R14.5, R14.6, R15.1, R15.2, decision-002): ``execute`` redacts the
message, rejects unadvertised extensions, update-with-starts the task's workflow and
streams the workflow's event log into the SDK's queue. The core loop never runs here."""

from __future__ import annotations

import json
import logging
from typing import Literal, cast

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, TaskState
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError, UnsupportedOperationError
from google.protobuf import json_format, struct_pb2
from pydantic import BaseModel, ConfigDict, ValidationError
from temporalio.client import Client, WithStartWorkflowOperation
from temporalio.common import SearchAttributePair, TypedSearchAttributes, WorkflowIDConflictPolicy

from tiny_harness.harness.core import (
    AgentState,
    HarnessTask,
    Participant,
    Role,
    TaskExtensionData,
    participant_of,
)
from tiny_harness.harness.security import Redactor
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.bridge import EventBridge
from tiny_harness.service.a2a.card import EVENT_MEDIA_TYPE, SUPPORTED_EXTENSIONS
from tiny_harness.service.a2a.task_store import AccessPolicy, asserted_participant
from tiny_harness.service.durable.models import InboxReceipt, TaskStart, WorkflowConfig
from tiny_harness.service.durable.workflows import (
    A2A_CONTEXT_ID,
    A2A_TASK_STATE,
    TINY_HARNESS_AGENT,
    TaskWorkflow,
)

log = logging.getLogger("tiny_harness.a2a.executor")


class EventEnvelope(BaseModel):
    """The task extension's event part: a ``Task`` payload creates or updates the extension
    data; status and artifact updates from a remote agent route to its sub-task (R15.1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["task", "status_update", "artifact_update"]
    payload: JsonObject


def redact_message(redactor: Redactor, message: Message) -> Message:
    """Scrub every text and data part before the message enters Temporal history."""
    clean = Message()
    clean.CopyFrom(message)
    for part in clean.parts:
        if part.HasField("text"):
            part.text = redactor.scrub_text(part.text)
        elif part.HasField("data"):
            raw = json_format.MessageToDict(part.data)
            scrubbed = redactor.scrub_value(raw)
            value = struct_pb2.Value()
            json_format.ParseDict(cast(JsonObject, scrubbed), value)
            part.data.CopyFrom(value)
    return clean


def message_text(message: Message) -> str:
    return "\n".join(p.text for p in message.parts if p.HasField("text"))


def envelope_of(message: Message) -> EventEnvelope | None:
    for part in message.parts:
        if part.HasField("data") and part.media_type == EVENT_MEDIA_TYPE:
            raw = json_format.MessageToDict(part.data)
            try:
                return EventEnvelope.model_validate(raw)
            except ValidationError as exc:
                raise InvalidParamsError(message=f"invalid event envelope: {exc}") from exc
    return None


def default_extension(message: Message, agent: str) -> TaskExtensionData:
    text = message_text(message).strip()
    first = text.splitlines()[0] if text else "task"
    participants: list[Participant] = [Participant(id=agent, kind="agent", role=Role.ASSIGNEE)]
    reporter = participant_of(message)
    if reporter:
        participants.insert(0, Participant(id=reporter, kind="human", role=Role.REPORTER))
    return TaskExtensionData(name=first[:60], goal=text or first, participants=tuple(participants))


def extension_from_envelope(
    envelope: EventEnvelope, message: Message, agent: str
) -> TaskExtensionData:
    try:
        ext = TaskExtensionData.model_validate(envelope.payload)
    except ValidationError as exc:
        raise InvalidParamsError(message=f"invalid task extension: {exc}") from exc
    if not any(p.role is Role.ASSIGNEE for p in ext.participants):
        ext = ext.model_copy(
            update={
                "participants": (
                    *ext.participants,
                    Participant(id=agent, kind="agent", role=Role.ASSIGNEE),
                )
            }
        )
    return ext


class HarnessExecutor(AgentExecutor):
    def __init__(
        self,
        client: Client,
        *,
        task_queue: str,
        bridge: EventBridge,
        config: WorkflowConfig,
        redactor: Redactor | None = None,
        policy: AccessPolicy | None = None,
    ) -> None:
        self._client = client
        self._task_queue = task_queue
        self._bridge = bridge
        self._config = config
        self._redactor = redactor or Redactor()
        self._policy = policy or AccessPolicy()

    def check_extensions(self, requested: set[str]) -> None:
        unknown = sorted(requested - set(SUPPORTED_EXTENSIONS))
        if unknown:
            raise UnsupportedOperationError(
                message=f"unsupported A2A extension(s): {', '.join(unknown)}"
            )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        self.check_extensions(context.requested_extensions)
        message = context.message
        if message is None or context.task_id is None or context.context_id is None:
            raise InvalidParamsError(message="a message with task and context ids is required")
        existing = context.current_task
        if existing is not None and not self._policy.allows(existing, context.call_context):
            raise TaskNotFoundError
        if existing is not None and existing.status.state in (
            TaskState.TASK_STATE_COMPLETED,
            TaskState.TASK_STATE_CANCELED,
            TaskState.TASK_STATE_FAILED,
            TaskState.TASK_STATE_REJECTED,
        ):
            raise UnsupportedOperationError(message="the task is in a terminal state")
        message = redact_message(self._redactor, message)
        message.task_id = context.task_id
        message.context_id = context.context_id
        participant = participant_of(message) or asserted_participant(context.call_context)
        if participant is None:  # fail closed (abuse case 4): nothing is created for nobody
            raise InvalidParamsError(message="no participant asserted")
        if participant_of(message) is None:
            message.metadata.update({"participant_id": participant})
        envelope = envelope_of(message)
        agent = self._config.agent
        ext = (
            extension_from_envelope(envelope, message, agent)
            if envelope is not None and envelope.kind == "task"
            else default_extension(message, agent)
        )
        task = HarnessTask.new(context.task_id, context.context_id, ext)
        start = TaskStart(
            task=task.proto,
            state=AgentState(task_id=task.id),
            config=self._config,
            correlation_id=task.id,
        )
        receipt = await self._update_with_start(start, message)
        if not receipt.accepted and not receipt.duplicate:
            raise TaskNotFoundError
        async for event in self._bridge.events(task.id, receipt.cursor):
            await event_queue.enqueue_event(event)

    async def _update_with_start(self, start: TaskStart, message: Message) -> InboxReceipt:
        task = HarnessTask(start.task)
        attributes = None
        if self._config.search_attributes:
            attributes = TypedSearchAttributes(
                [
                    SearchAttributePair(A2A_CONTEXT_ID, task.context_id),
                    SearchAttributePair(A2A_TASK_STATE, task.state_name),
                    SearchAttributePair(TINY_HARNESS_AGENT, self._config.agent),
                ]
            )
        operation: WithStartWorkflowOperation[TaskWorkflow, object] = WithStartWorkflowOperation(
            TaskWorkflow.run,
            start,
            id=task.id,
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            search_attributes=attributes,
        )
        return await self._client.execute_update_with_start_workflow(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message, start_workflow_operation=operation
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if task is None or not self._policy.allows(task, context.call_context):
            raise TaskNotFoundError
        page = await self._bridge.page(task.id, 0)
        cursor = page.next_seq if page is not None else 0
        handle = self._client.get_workflow_handle(task.id)
        await handle.signal(TaskWorkflow.cancel, "cancelled by client")
        async for event in self._bridge.events(task.id, cursor):
            await event_queue.enqueue_event(event)


def envelope_json(kind: str, payload: JsonObject) -> str:
    return json.dumps({"kind": kind, "payload": payload})


__all__ = [
    "EventEnvelope",
    "HarnessExecutor",
    "Part",
    "default_extension",
    "envelope_json",
    "envelope_of",
    "extension_from_envelope",
    "message_text",
    "redact_message",
]
