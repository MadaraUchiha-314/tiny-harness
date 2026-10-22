"""The A2A executor (R14.5, R14.6, R15.1, R15.2, decision-002): ``execute`` redacts the
message, rejects unadvertised extensions, update-with-starts the task's workflow and
streams the workflow's event log into the SDK's queue. The core loop never runs here.

Media (issue-38 design critic 5): before redaction, ``execute`` runs the media guard in
``extract`` mode (file parts are stored and rewritten to media URLs) and ``control`` in
``refuse`` mode. A refused file answers ``InvalidParams`` with the reason and the limit,
and nothing reaches the workflow."""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import AsyncGenerator, Collection, Iterable
from typing import Literal, cast

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.types import Message, Part, Task, TaskState
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError, UnsupportedOperationError
from google.protobuf import json_format
from pydantic import ValidationError
from temporalio.client import Client, WithStartWorkflowOperation, WorkflowUpdateFailedError
from temporalio.common import SearchAttributePair, TypedSearchAttributes, WorkflowIDConflictPolicy
from temporalio.service import RPCError

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.core import (
    AgentState,
    HarnessTask,
    Participant,
    Role,
    TaskExtensionData,
    participant_of,
)
from tiny_harness.harness.media import MediaIntake, MediaRejected, guard
from tiny_harness.harness.media.intake import is_file_part
from tiny_harness.harness.media.spans import intake_span
from tiny_harness.harness.security import Redactor
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.bridge import EventBridge
from tiny_harness.service.a2a.card import SUPPORTED_EXTENSIONS
from tiny_harness.service.a2a.task_store import (
    AccessPolicy,
    asserted_participant,
    strict_participant,
)
from tiny_harness.service.durable.models import InboxReceipt, TaskStart, WorkflowConfig
from tiny_harness.service.durable.workflows import (
    A2A_CONTEXT_ID,
    A2A_TASK_STATE,
    TINY_HARNESS_AGENT,
    TaskWorkflow,
)
from tiny_harness.service.inbox import (
    EVENT_MEDIA_TYPE,
    EventEnvelope,
    controls_task,
    envelope_of,
    server_controlled,
)

log = logging.getLogger("tiny_harness.a2a.executor")


def redact_message(redactor: Redactor, message: Message) -> Message:
    """Scrub the whole message, every string of every field (parts, their metadata, the
    message metadata, extensions), before it enters Temporal history (abuse case 6)."""
    raw = json_format.MessageToDict(message)
    scrubbed = redactor.scrub_value(raw)
    clean = Message()
    json_format.ParseDict(cast(JsonObject, scrubbed), clean)
    return clean


def media_refused(exc: MediaRejected) -> InvalidParamsError:
    """A refused file as the A2A error the client gets: the message, and the reason, the
    limit and the part index as the error's data (issue-38 R1.3)."""
    return InvalidParamsError(message=exc.message, data=dict(exc.detail))


FILE_PART_ALLOWANCE = 1_024
"""What a file part counts toward a message's size: its rewritten ``url`` part and
metadata, never its bytes, which go to the media store."""


def check_message_size(message: Message, limit: int | None) -> None:
    """Refuse a message whose serialized form, with each file part counted as its
    rewritten url part, is larger than ``limit`` (``[server] max_request_bytes``;
    self-review 2.2). With ``[media]`` the routes admit a full message of media, but the
    message itself goes to the workflow inbox, whose payload Temporal bounds at 2 MB."""
    if limit is None:
        return
    probe = Message()
    probe.CopyFrom(message)
    files = 0
    for part in probe.parts:
        if is_file_part(part) and part.WhichOneof("content") == "raw":
            part.raw = b""
            files += 1
    size = len(json_format.MessageToJson(probe, indent=None)) + files * FILE_PART_ALLOWANCE
    if size > limit:
        raise InvalidParamsError(
            message=f"the message is larger than {limit} bytes",
            data={"reason": "message_too_large", "limit": str(limit)},
        )


def message_text(message: Message) -> str:
    return "\n".join(p.text for p in message.parts if p.HasField("text"))


TERMINAL_STATES = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_REJECTED,
    }
)


def refuse_terminal(task: Task) -> None:
    """A message, command, completion or cancellation of a terminal task is refused with
    its state named (issue-25 R5.3)."""
    if task.status.state in TERMINAL_STATES:
        name = TaskState.Name(task.status.state)
        raise UnsupportedOperationError(message=f"the task is in a terminal state ({name})")


def refuse_watcher(task: Task, participant: str | None) -> None:
    """Only a participant in a role other than ``watcher`` cancels (abuse case 4)."""
    if not controls_task(HarnessTask(task).ext, participant):
        raise UnsupportedOperationError(message="a watcher cannot cancel the task")


def default_extension(message: Message, agent: str) -> TaskExtensionData:
    text = message_text(message).strip()
    first = text.splitlines()[0] if text else "task"
    participants: list[Participant] = [Participant(id=agent, kind="agent", role=Role.ASSIGNEE)]
    reporter = participant_of(message)
    if reporter:
        participants.insert(0, Participant(id=reporter, kind="human", role=Role.REPORTER))
    return TaskExtensionData(name=first[:60], goal=text or first, participants=tuple(participants))


def extension_from_envelope(
    envelope: EventEnvelope, message: Message, agent: str, *, trusted: bool = False
) -> TaskExtensionData:
    """A new task's extension from its first message's ``task`` envelope. An envelope that
    sets a server-controlled field is refused whole and no task is created (abuse case 1),
    unless its sender is a ``trusted`` delegator: the harness itself, or a peer the operator
    names in ``[server] delegators``, may brief a child fully (issue-34 R7, abuse case 5)."""
    refused = [] if trusted else server_controlled(envelope.payload)
    if refused:
        raise UnsupportedOperationError(
            message=f"task envelope cannot set server-controlled {', '.join(refused)}"
        )
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
    sender = participant_of(message)
    if sender is not None and not ext.is_participant(sender):
        # The creator reports the task it created, as with a plain first message; intake
        # takes messages from participants only (issue-34 R7.2).
        reporter = Participant(id=sender, kind="human", role=Role.REPORTER)
        ext = ext.model_copy(update={"participants": (reporter, *ext.participants)})
    return ext


def check_model(ext: TaskExtensionData, selectable: Collection[str]) -> None:
    """A briefed ``model`` must be one the configuration allows, as ``/model`` requires;
    trust lets a delegator set the field, never choose an arbitrary model (issue-34 abuse
    case 6)."""
    if ext.model is not None and ext.model not in selectable:
        raise UnsupportedOperationError(message=f"model {ext.model!r} is not selectable here")


def without_envelope(message: Message) -> Message:
    """The first message once its ``task`` envelope has made the task: intake must not
    apply it a second time as a change by a participant (issue-34 R7.2)."""
    kept = [p for p in message.parts if p.media_type != EVENT_MEDIA_TYPE]
    del message.parts[:]
    message.parts.extend(kept)
    return message


def sender_of(message: Message, call_context: ServerCallContext | None) -> str:
    """Who sends ``message``, written into its ``participant_id``. The request's asserted
    participant (``X-Participant-Id``, authenticated at the perimeter) decides: a message
    whose metadata names someone else is refused, so a watcher cannot complete, cancel or
    run a command as the reporter (issue-25 abuse case 4). Without a request assertion the
    message's own (decision-003); with neither, fail closed."""
    asserted = asserted_participant(call_context)
    if asserted is None and strict_participant(call_context):
        # The host's resolver named nobody; the message's own claim would bypass the
        # host's authentication (issue-36 abuse case 1). Fail closed.
        raise InvalidParamsError(message="no participant asserted")
    claimed = participant_of(message)
    if asserted is not None and claimed is not None and claimed != asserted:
        raise InvalidParamsError(message="the message names a different participant")
    participant = asserted or claimed
    if participant is None:  # fail closed (abuse case 4): nothing is created for nobody
        raise InvalidParamsError(message="no participant asserted")
    message.metadata.update({"participant_id": participant})
    return participant


class HarnessExecutor(AgentExecutor):
    # The extensions a request may activate: the card's (the media one too, with [media]).
    _extensions: frozenset[str] = frozenset(SUPPORTED_EXTENSIONS)

    def __init__(
        self,
        client: Client,
        *,
        task_queue: str,
        bridge: EventBridge,
        config: WorkflowConfig,
        redactor: Redactor | None = None,
        policy: AccessPolicy | None = None,
        delegators: Iterable[str] = (),
        models: Collection[str] | None = None,
        media_intake: MediaIntake | None = None,
        extensions: Collection[str] = SUPPORTED_EXTENSIONS,
        max_request_bytes: int | None = None,
    ) -> None:
        self._client = client
        self._max_message_bytes = max_request_bytes  # None: not checked (tests)
        self._extensions = frozenset(extensions)
        self._media = media_intake  # None: media off, every file part is refused
        # Who may brief a new task fully (issue-34 R7): this agent itself, always.
        self._delegators = frozenset({config.agent, *delegators})
        self._models = models  # the selectable models; None: not checked (tests)
        self._task_queue = task_queue
        self._bridge = bridge
        self._config = config
        self._redactor = redactor or Redactor()
        self._policy = policy or AccessPolicy()

    def check_extensions(self, requested: set[str]) -> None:
        unknown = sorted(requested - self._extensions)
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
        if existing is not None:
            refuse_terminal(existing)
        # Before intake, so a refused message stores nothing (self-review 2.2).
        check_message_size(message, self._max_message_bytes)
        if any(is_file_part(p) for p in message.parts):
            # Media is stored only for an asserted participant (fail closed), checked on a
            # copy: the message's own participant is written after redaction, as always.
            probe = Message()
            probe.CopyFrom(message)
            sender_of(probe, context.call_context)
        files = [p for p in message.parts if is_file_part(p)]
        observed = (
            intake_span(context.task_id, count=len(files), size=sum(len(p.raw) for p in files))
            if files
            else contextlib.nullcontext()
        )
        with observed as span:
            try:  # before redaction: the redactor never scans file bytes (abuse case 8)
                message = await guard(
                    message, allow="extract", intake=self._media, task_id=context.task_id
                )
            except MediaRejected as exc:
                if span is not None:
                    span.set(rejection=exc.reason)
                raise media_refused(exc) from exc
        message = redact_message(self._redactor, message)
        message.task_id = context.task_id
        message.context_id = context.context_id
        sender = sender_of(message, context.call_context)
        envelope = envelope_of(message)
        if envelope is not None and envelope.kind == "control" and existing is None:
            raise UnsupportedOperationError(message="a control needs an existing task")
        agent = self._config.agent
        trusted = sender in self._delegators
        briefed = envelope is not None and envelope.kind == "task" and existing is None
        if briefed:
            assert envelope is not None
            ext = extension_from_envelope(envelope, message, agent, trusted=trusted)
            if self._models is not None:
                check_model(ext, self._models)
            message = without_envelope(message)
        else:
            ext = default_extension(message, agent)
        # A task assigned to someone other than this agent is theirs to do: it makes no
        # model call and waits for its assignee (R12.3; issue-34 R7.2).
        assignee = next((p.id for p in ext.participants if p.role is Role.ASSIGNEE), agent)
        mode: Literal["agent", "participant"] = "agent" if assignee == agent else "participant"
        if mode == "participant":
            ext = ext.model_copy(
                update={"lifecycle": None, "model": None, "reasoning_effort": None}
            )
        elif not (trusted and ext.lifecycle == "delegated"):
            # A participant's first message opens a conversation; only the server, or a
            # trusted delegator briefing a child, sets this (R3, issue-34 R7).
            ext = ext.model_copy(update={"lifecycle": "conversation"})
        task = HarnessTask.new(context.task_id, context.context_id, ext)
        start = TaskStart(
            task=task.proto,
            state=AgentState(task_id=task.id),
            mode=mode,
            config=self._config,
            correlation_id=task.id,
        )
        if briefed and not message.parts:
            # A brief and nothing else: the task starts without a message for its model, as
            # a /sub-task or a participant task does (issue-34 R7.2).
            await self._start(start)
            async for event in self._bridge.events(task.id, 0):
                await event_queue.enqueue_event(event)
            return
        try:
            receipt = await self._update_with_start(start, message)
        except WorkflowUpdateFailedError as exc:  # the inbox validator refused it
            cause = exc.cause
            reason = getattr(cause, "message", None) or str(cause or exc)
            raise UnsupportedOperationError(message=f"message refused: {reason}") from exc
        if not receipt.accepted and not receipt.duplicate:
            raise TaskNotFoundError
        async for event in self._bridge.events(task.id, receipt.cursor):
            await event_queue.enqueue_event(event)

    async def control(
        self, task: Task, message: Message, call_context: ServerCallContext | None
    ) -> AsyncGenerator[A2AEvent]:
        """A control for an existing task (issue-25 R5.1, R5.2), delivered outside the
        SDK's per-task request queue: that queue runs one ``execute`` at a time, so a
        completion would otherwise wait for the very turn it must interrupt. The caller
        has applied the access policy and the terminal check; the inbox update's
        validator authorizes the sender's role before anything is interrupted. A control
        carries no files (issue-38 design critic 5)."""
        try:
            message = await guard(message, allow="refuse")
        except MediaRejected as exc:
            raise media_refused(exc) from exc
        check_message_size(message, self._max_message_bytes)
        message = redact_message(self._redactor, message)
        message.task_id = task.id
        message.context_id = task.context_id
        sender_of(message, call_context)
        handle = self._client.get_workflow_handle_for(TaskWorkflow.run, task.id)
        try:
            receipt = await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
                TaskWorkflow.inbox, message
            )
        except WorkflowUpdateFailedError as exc:
            cause = exc.cause
            reason = getattr(cause, "message", None) or str(cause or exc)
            raise UnsupportedOperationError(message=f"message refused: {reason}") from exc
        except RPCError as exc:  # the workflow is gone
            raise TaskNotFoundError from exc
        yield task
        if receipt.duplicate:  # already handled: no new events will follow (critic B2)
            return
        async for event in self._bridge.events(task.id, receipt.cursor):
            yield event

    def _attributes(self, task: HarnessTask) -> TypedSearchAttributes | None:
        if not self._config.search_attributes:
            return None
        return TypedSearchAttributes(
            [
                SearchAttributePair(A2A_CONTEXT_ID, task.context_id),
                SearchAttributePair(A2A_TASK_STATE, task.state_name),
                SearchAttributePair(TINY_HARNESS_AGENT, self._config.agent),
            ]
        )

    async def _start(self, start: TaskStart) -> None:
        """Start the task's workflow with no message in its inbox."""
        task = HarnessTask(start.task)
        await self._client.start_workflow(
            TaskWorkflow.run,
            start,
            id=task.id,
            task_queue=self._task_queue,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            search_attributes=self._attributes(task),
        )

    async def _update_with_start(self, start: TaskStart, message: Message) -> InboxReceipt:
        task = HarnessTask(start.task)
        attributes = self._attributes(task)
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
        refuse_terminal(task)
        refuse_watcher(task, asserted_participant(context.call_context))
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
    "check_model",
    "default_extension",
    "envelope_json",
    "envelope_of",
    "extension_from_envelope",
    "media_refused",
    "message_text",
    "redact_message",
    "refuse_terminal",
    "refuse_watcher",
]
