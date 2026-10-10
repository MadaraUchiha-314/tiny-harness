"""The task workflow (R19, decision-002): the core loop over an activity-backed port.

The workflow never calls a model or a tool; every operation is an activity whose typed
result is recorded in history (R19.2). Attempts are workflow-managed: each activity is
scheduled with ``maximum_attempts=1`` and, on failure, the ``dispatch_hooks`` activity
runs ``activity.failed.pre`` and ``activity.retried.pre`` before the next attempt (R19.3,
R19.4). The mailbox is the inbox (R15): the ``inbox`` update appends, the loop drains at
the top of each turn, and an idle task waits in ``wait_condition`` (R19.7). The durable
event log is what the A2A server streams and replays (R14.5, R15.6).

Sandbox (R19.9): the modules passed through are ``tiny_harness.harness`` and this
layer's models (pure Pydantic and protobuf models), ``pydantic`` (as Temporal's Pydantic
integration requires), ``a2a`` and ``google.protobuf`` (the SDK's generated types),
``jsonschema`` and ``packaging`` (pulled by the core models). None of them is called for
time, randomness or I/O from workflow code.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Final, cast

from temporalio import workflow
from temporalio.common import RetryPolicy, SearchAttributeKey
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

with workflow.unsafe.imports_passed_through():
    from a2a.types import (
        Artifact,
        Message,
        Part,
        Task,
        TaskArtifactUpdateEvent,
        TaskState,
        TaskStatus,
        TaskStatusUpdateEvent,
    )
    from a2a.types import Role as A2ARole
    from google.protobuf import struct_pb2

    from tiny_harness.config import RetryPolicySpec
    from tiny_harness.harness.channels import (
        CHANNEL_EXT_MEDIA_TYPE,
        ChannelMessage,
        ChannelMessageData,
    )
    from tiny_harness.harness.core import (
        AcceptanceCriterion,
        AgentState,
        CompactionRecord,
        CompletionDecision,
        ContextWindow,
        CoreLoop,
        HarnessTask,
        Participant,
        Role,
        TaskCompleteIn,
        TaskExtensionData,
        TaskRef,
        state_name,
    )
    from tiny_harness.harness.entities import EntityKind, EntityRef
    from tiny_harness.harness.models import LLMRequest, LLMResponse, MessageItem, extract_tool_calls
    from tiny_harness.harness.models import Role as MessageRole
    from tiny_harness.harness.security import Redactor
    from tiny_harness.harness.tools import (
        ContentPart,
        Idempotency,
        ToolCall,
        ToolResult,
        WorkflowCommand,
    )
    from tiny_harness.interaction.a2ui import (
        A2UI_MEDIA_TYPE,
        ServerMessage,
        SurfaceRegistry,
        parse_server_message,
    )
    from tiny_harness.jsontypes import JsonObject
    from tiny_harness.service.durable.models import (
        ActivityIn,
        ActivityName,
        AssembleIn,
        ChannelSendIn,
        ChildDone,
        ChildRef,
        CompactIn,
        CompactOut,
        CompletionIn,
        CompletionOut,
        EmitIn,
        ErrorInfo,
        EventEntry,
        EventPage,
        HeartbeatResult,
        HeartbeatTick,
        HelpRequest,
        InboxReceipt,
        IntakeIn,
        IntakeOut,
        LLMIn,
        LLMTurn,
        MonitorIn,
        MonitorSnapshot,
        PersistIn,
        PollIn,
        PollOut,
        RemoteStart,
        RemoteTurnIn,
        RemoteTurnOut,
        RetryIn,
        RetryOut,
        SweepIn,
        SweepOut,
        TaskMonitor,
        TaskStart,
        ToolIn,
        ToolOut,
        TriggerIn,
        TriggerOut,
        event_entry,
    )

A2A_CONTEXT_ID = SearchAttributeKey.for_keyword("A2AContextId")
A2A_TASK_STATE = SearchAttributeKey.for_keyword("A2ATaskState")
TINY_HARNESS_AGENT = SearchAttributeKey.for_keyword("TinyHarnessAgent")

ONE_ATTEMPT: Final = RetryPolicy(maximum_attempts=1)
EVENT_TAIL: Final = 1000
DEFAULT_TIMEOUT: Final = timedelta(seconds=60)
TERMINAL_NAMES: Final = frozenset({"COMPLETED", "FAILED", "CANCELED", "REJECTED"})
TERMINAL: Final = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
    }
)


def backoff(spec: RetryPolicySpec, attempt: int) -> timedelta:
    """``initial * coefficient^(attempt-1)`` capped at the maximum, jittered by 20 %."""
    seconds = spec.initial_interval.total_seconds() * spec.backoff_coefficient ** (attempt - 1)
    seconds = min(seconds, spec.maximum_interval.total_seconds())
    return timedelta(seconds=seconds * (0.8 + 0.4 * workflow.random().random()))


def is_non_retryable(info: ErrorInfo, spec: RetryPolicySpec) -> bool:
    """A failure the policy never retries: flagged by the activity, or of a type the
    effective policy lists in ``non_retryable_error_types`` (R19.3)."""
    return info.non_retryable or info.type in spec.non_retryable_error_types


def _error_info(exc: ActivityError) -> ErrorInfo:
    cause = exc.cause
    if isinstance(cause, ApplicationError):
        return ErrorInfo(
            type=cause.type or "error", message=cause.message, non_retryable=cause.non_retryable
        )
    return ErrorInfo(
        type=type(cause).__name__ if cause else "ActivityError", message=str(cause or exc)
    )


def text_message(task: HarnessTask, text: str, *, message_id: str) -> Message:
    return Message(
        message_id=message_id,
        context_id=task.context_id,
        task_id=task.id,
        role=A2ARole.ROLE_AGENT,
        parts=[Part(text=text)],
    )


class WorkflowOperations:
    """The loop's port, bound to the workflow: every method is one or more activities."""

    def __init__(self, wf: TaskWorkflow) -> None:
        self._wf = wf
        self._turn: LLMTurn | None = None
        self._window: ContextWindow | None = None

    def _arg[T: ActivityIn](self, model: type[T], **fields: object) -> T:
        wf = self._wf
        return model(task_id=wf.task.id, correlation_id=wf.correlation_id, **fields)  # type: ignore[arg-type]

    async def ingest(self, task: HarnessTask, state: AgentState, text: str) -> AgentState:
        return state.append(MessageItem(role=MessageRole.USER, text=text))

    async def drain(self, task: HarnessTask, state: AgentState) -> AgentState:
        state, _ = await self._wf.drain(task, state)
        return state

    async def assemble(self, task: HarnessTask, state: AgentState) -> ContextWindow:
        window = await self._wf.call(
            ActivityName.ASSEMBLE_CONTEXT,
            self._arg(AssembleIn, task=task.proto, state=state),
            ContextWindow,
        )
        self._window = window
        return window

    async def should_compact(self, task: HarnessTask, window: ContextWindow) -> bool:
        out = await self._wf.call(
            ActivityName.COMPACTION_TRIGGER,
            self._arg(TriggerIn, task=task.proto, window=window),
            TriggerOut,
        )
        return out.compact

    async def compact(
        self, task: HarnessTask, state: AgentState, window: ContextWindow
    ) -> tuple[AgentState, CompactionRecord]:
        out = await self._wf.call(
            ActivityName.COMPACT,
            self._arg(CompactIn, task=task.proto, state=state, window=window),
            CompactOut,
        )
        return out.state, out.record

    async def invoke_llm(self, task: HarnessTask, request: LLMRequest) -> LLMResponse:
        turn = await self._wf.call(
            ActivityName.INVOKE_LLM, self._arg(LLMIn, task=task.proto, request=request), LLMTurn
        )
        self._turn = turn
        return turn.response

    async def extract(self, task: HarnessTask, response: LLMResponse) -> tuple[ToolCall, ...]:
        turn = self._turn
        if turn is not None and turn.response == response:
            return turn.calls
        return extract_tool_calls(response)

    def _idempotent(self, name: str) -> bool:
        window = self._window
        if window is None:
            return False
        for definition in window.tools:
            if definition.name == name:
                return definition.idempotency is Idempotency.IDEMPOTENT
        return False

    async def invoke_tool(self, task: HarnessTask, call: ToolCall) -> ToolResult | WorkflowCommand:
        idempotent = self._idempotent(call.name)
        try:
            out = await self._wf.call(
                ActivityName.INVOKE_TOOL,
                self._arg(ToolIn, task=task.proto, actor=self._wf.actor, call=call),
                ToolOut,
                idempotent=idempotent,
            )
        except ApplicationError as exc:
            code = exc.type or "activity.failed"
            if not idempotent and code != "hook.abort":
                code = "tool.not_retried"
            return ToolResult.error(call.call_id, code, exc.message)
        return out.result

    async def decide_completion(self, task: HarnessTask) -> TaskCompleteIn:
        unresolved = self._wf.unresolved()
        out = await self._wf.call(
            ActivityName.DECIDE_COMPLETION,
            self._arg(CompletionIn, task=task.proto, unresolved=unresolved),
            CompletionOut,
        )
        return TaskCompleteIn(
            task_id=task.id,
            correlation_id=self._wf.correlation_id,
            unresolved=unresolved,
            result=CompletionDecision(out.result),
            reason=out.reason,
        )

    async def spawn(self, task: HarnessTask, command: WorkflowCommand) -> TaskRef:
        return await self._wf.spawn_child(task, command)

    async def record(
        self, task: HarnessTask, state: AgentState, compaction: CompactionRecord | None
    ) -> None:
        self._wf.task, self._wf.state = task, state
        await self._wf.persist(compaction)

    async def set_state(self, task: HarnessTask, state: int) -> HarnessTask:
        return await self._wf.set_status(task, state)

    async def wait_for_reply(self, task: HarnessTask, help: JsonObject) -> HarnessTask:
        return await self._wf.ask(task, help)

    async def complete(self, task: HarnessTask, text: str) -> HarnessTask:
        return await self._wf.set_status(task, TaskState.TASK_STATE_COMPLETED, text=text)

    async def emit_ui(self, task: HarnessTask, command: WorkflowCommand) -> None:
        await self._wf.emit_ui(task, command)

    async def fail(self, task: HarnessTask, reason: str) -> HarnessTask:
        return await self._wf.set_status(task, TaskState.TASK_STATE_FAILED, text=reason)


@workflow.defn(name="TaskWorkflow")
class TaskWorkflow:
    def __init__(self) -> None:
        self.task: HarnessTask = HarnessTask(Task())
        self.state: AgentState = AgentState(task_id="")
        self.start: TaskStart = TaskStart(task=Task(), state=AgentState(task_id=""))
        self.correlation_id = ""
        self.actor: str | None = None
        self.mailbox: list[Message] = []
        self.seen: set[str] = set()
        self.events: list[EventEntry] = []
        self.next_seq = 0
        self.pending_help: HelpRequest | None = None
        self.children: list[ChildRef] = []
        self.notes: list[str] = []
        self.attempts: dict[str, int] = {}
        self.cancel_reason: str | None = None
        self.interrupted = False
        self.closed = False
        self.turns_this_run = 0
        self.last_refusal = ""
        self.surfaces = SurfaceRegistry()
        self._redactor = Redactor()

    # --- handlers ------------------------------------------------------------------

    @workflow.update
    async def inbox(self, message: Message) -> InboxReceipt:
        mid = message.message_id
        if mid in self.seen:
            return InboxReceipt(
                message_id=mid,
                accepted=False,
                duplicate=True,
                state_name=self.task.state_name,
                cursor=self.next_seq,
            )
        self.seen.add(mid)
        self.mailbox.append(message)
        if message.HasField("metadata") and "interrupt" in message.metadata.fields:
            self.interrupted = bool(message.metadata.fields["interrupt"].bool_value)
        return InboxReceipt(
            message_id=mid, accepted=True, state_name=self.task.state_name, cursor=self.next_seq
        )

    @inbox.validator
    def _inbox_validator(self, message: Message) -> None:
        if self.closed:
            raise ValueError("task is closed")

    @workflow.signal
    async def cancel(self, reason: str) -> None:
        self.cancel_reason = reason or "cancelled"

    @workflow.signal
    async def child_done(self, done: ChildDone) -> None:
        """A child's state change; terminal states resolve it, others are relayed (R7.3)."""
        terminal = done.state_name in TERMINAL_NAMES
        for i, child in enumerate(self.children):
            if child.task_id == done.task_id:
                self.children[i] = child.model_copy(
                    update={
                        "done": terminal,
                        "state_name": done.state_name,
                        "summary": done.summary,
                    }
                )
        self.notes.append(f"Sub-task {done.task_id} is {done.state_name}: {done.summary}".strip())

    @workflow.query(name="task")
    def task_query(self) -> Task:
        return self.task.proto

    @workflow.query
    def monitor(self) -> TaskMonitor:
        return TaskMonitor(
            task_id=self.task.id,
            context_id=self.task.context_id,
            state_name=self.task.state_name,
            mailbox=len(self.mailbox),
            pending_help=self.pending_help is not None,
            children=len([c for c in self.children if not c.done]),
            turn=self.state.turn,
        )

    @workflow.query
    def events_since(self, cursor: int) -> EventPage:
        return EventPage(
            events=tuple(e for e in self.events if e.seq >= cursor),
            next_seq=self.next_seq,
            closed=self.closed,
        )

    # --- the run -------------------------------------------------------------------

    @workflow.run
    async def run(self, start: TaskStart) -> Task:
        self._load(start)
        if start.next_event_seq == 0:
            self._emit(self.task.proto)
            if start.config.search_attributes:
                workflow.upsert_search_attributes(  # pyright: ignore[reportUnknownMemberType]
                    [
                        A2A_CONTEXT_ID.value_set(self.task.context_id),
                        TINY_HARNESS_AGENT.value_set(start.config.agent),
                        A2A_TASK_STATE.value_set(self.task.state_name),
                    ]
                )
        if start.mode == "participant":
            return await self._run_participant()
        loop = CoreLoop(WorkflowOperations(self), max_turns=start.config.max_turns)
        while True:
            await workflow.wait_condition(self._ready)
            if self.cancel_reason is not None:
                return await self._finish(TaskState.TASK_STATE_CANCELED, text=self.cancel_reason)
            if self.pending_help is not None and not self.notes:
                # Waiting for a reply: a refused message must not wake the loop (abuse case 4).
                self.state, accepted = await self.drain(self.task, self.state)
                if accepted == 0 and self.waiting_for_reply():
                    # The sender is a participant (strangers never reach the workflow), so
                    # the stream they opened ends with the unchanged state and the reason.
                    self.task = await self.set_status(
                        self.task,
                        self.task.state,
                        text=f"message not accepted: {self.last_refusal}",
                    )
                    continue
            runner = asyncio.create_task(loop.run(self.task, self.state, None))
            if not await self._await_runner(runner):
                if self.cancel_reason is not None:
                    return await self._finish(
                        TaskState.TASK_STATE_CANCELED, text=self.cancel_reason
                    )
                self.interrupted = False
                continue
            try:
                outcome = runner.result()
            except ApplicationError as exc:
                return await self._finish(TaskState.TASK_STATE_FAILED, text=exc.message)
            self.task, self.state = outcome.task, outcome.state
            if outcome.kind in ("waiting_for_reply", "waiting_for_children"):
                continue
            return await self._finish(None)

    def _ready(self) -> bool:
        return bool(self.mailbox) or bool(self.notes) or self.cancel_reason is not None

    def waiting_for_reply(self) -> bool:
        return self.pending_help is not None

    async def drain(self, task: HarnessTask, state: AgentState) -> tuple[AgentState, int]:
        """Top of a turn (R15.3): roll over if due, fold notes and accepted inbox messages
        into the history; returns how many messages intake accepted. The last refusal's
        reason is kept in ``last_refusal`` for the waiting path."""
        self.task = task
        await self.maybe_continue_as_new(task, state)
        self.turns_this_run += 1
        for note in self.take_notes():  # sub-task and remote-agent results: data, not orders
            state = state.append(MessageItem(role=MessageRole.USER, text=note, source="agent"))
        accepted = 0
        while self.mailbox:
            # The message leaves the mailbox only once its intake has completed: an
            # interrupt or a cancel during intake leaves it for the next drain (R15.5).
            message = self.mailbox[0]
            out = await self.call(
                ActivityName.INTAKE,
                IntakeIn(
                    task_id=task.id,
                    correlation_id=self.correlation_id,
                    task=task.proto,
                    message=message,
                    surfaces=self.surfaces,
                ),
                IntakeOut,
            )
            self.mailbox.pop(0)
            if not out.accepted:
                self.last_refusal = out.reason or "not accepted"
                continue
            accepted += 1
            text = out.text
            pending = self.pending_help
            if pending is not None and out.participant_id == pending.participant_id:
                self.pending_help = None
                text = f'Reply from {pending.participant_id} to "{pending.question}": {out.text}'
            elif out.participant_id:
                text = f"[{out.participant_id}] {out.text}"
            if out.participant_id:
                self.actor = out.participant_id
            state = state.append(MessageItem(role=MessageRole.USER, text=text, source=out.source))
            # Committed now, not at the end of the turn: an interrupt that cancels the
            # run restarts from ``self.state`` and must not lose what intake accepted.
            self.state = state
        return state, accepted

    async def _await_runner(self, runner: asyncio.Task[object]) -> bool:
        """Wait for the loop run; False when a cancel or an interrupt cut it short."""
        await workflow.wait_condition(
            lambda: runner.done() or self.cancel_reason is not None or self.interrupted
        )
        if runner.done():
            return True
        runner.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner
        return False

    async def _run_participant(self) -> Task:
        """A task assigned to a human: it waits for the assignee's message (R12.3)."""
        assignee = next((p.id for p in self.task.ext.participants if p.role is Role.ASSIGNEE), None)
        if self.task.state != TaskState.TASK_STATE_INPUT_REQUIRED:
            self.task = await self.set_status(
                self.task, TaskState.TASK_STATE_INPUT_REQUIRED, text=self.task.ext.goal
            )
        while True:
            await workflow.wait_condition(
                lambda: bool(self.mailbox) or self.cancel_reason is not None
            )
            if self.cancel_reason is not None:
                return await self._finish(TaskState.TASK_STATE_CANCELED, text=self.cancel_reason)
            message = self.mailbox.pop(0)
            out = await self.call(
                ActivityName.INTAKE,
                IntakeIn(
                    task_id=self.task.id,
                    correlation_id=self.correlation_id,
                    task=self.task.proto,
                    message=message,
                ),
                IntakeOut,
            )
            if not out.accepted or (assignee is not None and out.participant_id != assignee):
                continue
            self.state = self.state.append(MessageItem(role=MessageRole.USER, text=out.text))
            return await self._finish(TaskState.TASK_STATE_COMPLETED, text=out.text)

    async def _finish(self, state: int | None, *, text: str = "") -> Task:
        if state is not None:
            self.task = await self.set_status(self.task, state, text=text)
        if state == TaskState.TASK_STATE_CANCELED:
            for child in self.children:
                if not child.done:
                    with contextlib.suppress(Exception):
                        handle = workflow.get_external_workflow_handle(child.workflow_id)
                        await handle.signal("cancel", text or "parent cancelled")
        self.closed = True
        await self.persist(None, final=True)
        if self.start.parent_workflow_id:
            summary = text or self._last_assistant_text()
            handle = workflow.get_external_workflow_handle(self.start.parent_workflow_id)
            await handle.signal(
                "child_done",
                ChildDone(
                    task_id=self.task.id, state_name=self.task.state_name, summary=summary[:500]
                ),
            )
        return self.task.proto

    def _last_assistant_text(self) -> str:
        for entry in reversed(self.state.history):
            item = entry.item
            if isinstance(item, MessageItem) and item.role is MessageRole.ASSISTANT:
                return item.text
        return ""

    # --- state -------------------------------------------------------------------

    def _load(self, start: TaskStart) -> None:
        """Handlers may run before ``run`` (update-with-start delivers the first message in
        the same activation), so what they wrote is merged, never overwritten."""
        self.start = start
        self.task = HarnessTask(start.task)
        self.state = start.state
        self.correlation_id = start.correlation_id or workflow.info().workflow_id
        early = [m for m in self.mailbox if m.message_id not in start.seen_message_ids]
        self.mailbox = [*start.mailbox, *early]
        self.seen = set(start.seen_message_ids) | {m.message_id for m in self.mailbox}
        self.events = list(start.events)
        self.next_seq = start.next_event_seq
        self.pending_help = start.pending_help
        self.children = list(start.children)
        self.notes = [*start.notes, *self.notes]
        self.attempts = dict(start.attempt_counters)
        self.surfaces = start.surfaces

    def _snapshot(self, task: HarnessTask, state: AgentState) -> TaskStart:
        return self.start.model_copy(
            update={
                "task": task.proto,
                "state": state,
                "correlation_id": self.correlation_id,
                "mailbox": tuple(self.mailbox),
                "seen_message_ids": tuple(sorted(self.seen)),
                "events": tuple(self.events[-EVENT_TAIL:]),
                "next_event_seq": self.next_seq,
                "pending_help": self.pending_help,
                "children": tuple(self.children),
                "notes": tuple(self.notes),
                "attempt_counters": dict(self.attempts),
                "surfaces": self.surfaces,
            }
        )

    async def maybe_continue_as_new(self, task: HarnessTask, state: AgentState) -> None:
        """Roll over at the top of a turn once the history passes the bound, or when the
        server suggests it (R19.8); the first turn of a run always runs."""
        info = workflow.info()
        if self.turns_this_run == 0:
            return
        over = info.get_current_history_length() > self.start.config.history_event_bound
        if not over and not info.is_continue_as_new_suggested():
            return
        await workflow.wait_condition(workflow.all_handlers_finished)
        workflow.continue_as_new(self._snapshot(task, state))

    def take_notes(self) -> list[str]:
        notes, self.notes = self.notes, []
        return notes

    def unresolved(self) -> tuple[TaskRef, ...]:
        return tuple(TaskRef(task_id=c.task_id) for c in self.children if not c.done)

    # --- events ------------------------------------------------------------------

    def _emit(
        self, event: Task | Message | TaskStatusUpdateEvent | TaskArtifactUpdateEvent
    ) -> EventEntry:
        entry = event_entry(self.next_seq, event)
        self.events.append(entry)
        self.next_seq += 1
        return entry

    async def _deliver(self, entry: EventEntry) -> None:
        await workflow.execute_activity(
            ActivityName.EMIT_EVENT.value,
            EmitIn(
                task_id=self.task.id,
                correlation_id=self.correlation_id,
                context_id=self.task.context_id,
                entry=entry,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def set_status(
        self,
        task: HarnessTask,
        state: int,
        *,
        text: str | None = None,
        message: Message | None = None,
    ) -> HarnessTask:
        proto = Task()
        proto.CopyFrom(task.proto)
        status = TaskStatus(state=state, timestamp=workflow.now())  # type: ignore[arg-type]
        if message is None and text:
            message = text_message(task, text, message_id=f"{task.id}:status:{self.next_seq}")
        if message is not None:
            status.message.CopyFrom(message)
        proto.status.CopyFrom(status)
        updated = HarnessTask(proto)
        self.task = updated
        entry = self._emit(
            TaskStatusUpdateEvent(task_id=task.id, context_id=task.context_id, status=status)
        )
        if self.start.config.search_attributes:
            workflow.upsert_search_attributes(  # pyright: ignore[reportUnknownMemberType]
                [A2A_TASK_STATE.value_set(updated.state_name)]
            )
        await self._deliver(entry)
        return updated

    async def ask(self, task: HarnessTask, help: JsonObject) -> HarnessTask:
        participant_id = str(help.get("participant_id", ""))
        question = str(help.get("question", ""))
        raw_options = help.get("options")
        options = tuple(str(o) for o in raw_options) if isinstance(raw_options, list) else ()
        message_id = f"{task.id}:help:{self.next_seq}"
        text = question if not options else f"{question}\nOptions: {', '.join(options)}"
        data = ChannelMessageData(
            channel_id=task.id, sender=self.start.config.agent, kind="help_request", text=question
        )
        value = struct_pb2.Value()
        value.struct_value.update(data.model_dump(mode="json"))
        message = Message(
            message_id=message_id,
            context_id=task.context_id,
            task_id=task.id,
            role=A2ARole.ROLE_AGENT,
            parts=[Part(text=text), Part(data=value, media_type=CHANNEL_EXT_MEDIA_TYPE)],
        )
        await workflow.execute_activity(
            ActivityName.SEND_CHANNEL_MESSAGE.value,
            ChannelSendIn(
                task_id=task.id,
                correlation_id=self.correlation_id,
                task=task.proto,
                message=ChannelMessage(
                    id=message_id,
                    channel_id=task.id,
                    sender=self.start.config.agent,
                    parts=(ContentPart(kind="text", text=text),),
                    at=workflow.now(),
                    kind="help_request",
                ),
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self.pending_help = HelpRequest(
            participant_id=participant_id,
            question=question,
            options=options,
            message_id=message_id,
            call_id=str(help.get("call_id", "")),
        )
        return await self.set_status(task, TaskState.TASK_STATE_INPUT_REQUIRED, message=message)

    async def emit_ui(self, task: HarnessTask, command: WorkflowCommand) -> None:
        """``emit_ui`` (R20.5): the validated A2UI messages become one A2A message event
        with ``application/a2ui+json`` parts; the surfaces they create are remembered."""
        raw = command.payload.get("messages")
        payloads = [cast(JsonObject, m) for m in raw] if isinstance(raw, list) else []
        parts: list[Part] = []
        for payload in payloads:
            parsed: ServerMessage = parse_server_message(payload)
            self.surfaces = self.surfaces.apply(parsed)
            value = struct_pb2.Value()
            value.struct_value.update(payload)
            parts.append(Part(data=value, media_type=A2UI_MEDIA_TYPE))
        if not parts:
            return
        # The A2A SDK refuses a Message once a task exists ("task mode"), so the UI
        # travels as an artifact update: one artifact per emit_ui call, final chunk.
        event = TaskArtifactUpdateEvent(
            task_id=task.id,
            context_id=task.context_id,
            artifact=Artifact(artifact_id=f"a2ui:{self.next_seq}", name="a2ui", parts=parts),
            last_chunk=True,
        )
        entry = self._emit(event)
        await self._deliver(entry)

    async def persist(self, compaction: CompactionRecord | None, *, final: bool = False) -> None:
        await self.call(
            ActivityName.PERSIST,
            PersistIn(
                task_id=self.task.id,
                correlation_id=self.correlation_id,
                task=self.task.proto,
                state=self.state,
                compaction=compaction,
                events=tuple(self.events) if final else (),
                final=final,
            ),
            type(None),
        )

    # --- children ------------------------------------------------------------------

    async def spawn_child(self, task: HarnessTask, command: WorkflowCommand) -> TaskRef:
        payload = command.payload
        index = len(self.children) + 1
        child_id = f"{task.id}.{index}"
        name = str(payload.get("name", f"sub-task {index}"))
        goal = str(payload.get("goal", ""))
        raw_criteria = payload.get("acceptance_criteria")
        criteria = tuple(
            AcceptanceCriterion(text=str(c))
            for c in (raw_criteria if isinstance(raw_criteria, list) else [])
        )
        step = payload.get("step")
        participants = task.ext.participants
        mode: str = "agent"
        kind: str = "local"
        if command.kind == "create_participant_task":
            mode, kind = "participant", "participant"
            target = str(payload.get("participant_id", ""))
            participants = tuple(
                p.model_copy(
                    update={
                        "role": Role.ASSIGNEE
                        if p.id == target
                        else (Role.WATCHER if p.role is Role.ASSIGNEE else p.role)
                    }
                )
                for p in participants
            )
        elif not participants:
            participants = (
                Participant(id=self.start.config.agent, kind="agent", role=Role.ASSIGNEE),
            )
        ext = TaskExtensionData(
            name=name,
            goal=goal,
            acceptance_criteria=criteria,
            participants=participants,
            parent_tasks=(TaskRef(task_id=task.id),),
        )
        child = HarnessTask.new(child_id, task.context_id, ext)
        agent = payload.get("agent")
        if command.kind == "spawn_subtask" and agent:
            await workflow.start_child_workflow(
                "RemoteTaskWorkflow",
                RemoteStart(
                    task=child.proto,
                    agent=str(agent),
                    goal=goal,
                    parent_workflow_id=workflow.info().workflow_id,
                    correlation_id=self.correlation_id,
                    config=self.start.config,
                ),
                id=child_id,
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
            )
            self.children.append(
                ChildRef(
                    task_id=child_id,
                    workflow_id=child_id,
                    kind="remote",
                    step=str(step) if step else None,
                )
            )
            return TaskRef(task_id=child_id, agent=EntityRef(kind=EntityKind.AGENT, id=str(agent)))
        first = Message(
            message_id=f"{child_id}:goal",
            context_id=task.context_id,
            task_id=child_id,
            role=A2ARole.ROLE_USER,
            parts=[Part(text=goal)],
        )
        # The delegating agent is the sender, and a participant of the child: intake
        # refuses a message that asserts nobody (abuse case 4).
        first.metadata.update({"participant_id": self.start.config.agent})
        start = TaskStart(
            task=child.proto,
            state=AgentState(task_id=child_id),
            mode="participant" if mode == "participant" else "agent",
            config=self.start.config,
            correlation_id=self.correlation_id,
            mailbox=(first,) if mode == "agent" else (),
            parent_workflow_id=workflow.info().workflow_id,
        )
        await workflow.start_child_workflow(
            "TaskWorkflow",
            start,
            id=child_id,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        self.children.append(
            ChildRef(
                task_id=child_id,
                workflow_id=child_id,
                kind="participant" if kind == "participant" else "local",
                step=str(step) if step else None,
            )
        )
        return TaskRef(task_id=child_id)

    # --- the activity wrapper (R19.3-R19.6) -----------------------------------------

    def _policy(self, name: str, *, idempotent: bool) -> RetryPolicySpec:
        spec = self.start.config.retries.for_activity(name)
        if not idempotent:
            spec = spec.model_copy(update={"maximum_attempts": 1})
        return spec

    def _timeouts(self, name: ActivityName) -> tuple[timedelta, timedelta | None]:
        """LLM, tool and compaction activities heartbeat; the rest are short (R19.6)."""
        config = self.start.config
        if name is ActivityName.INVOKE_LLM or name is ActivityName.COMPACT:
            return config.llm_timeout, config.heartbeat_timeout
        if name is ActivityName.INVOKE_TOOL:
            return config.tool_timeout, config.heartbeat_timeout
        return DEFAULT_TIMEOUT, None

    async def call[T](
        self, name: ActivityName, arg: ActivityIn, result_type: type[T], *, idempotent: bool = True
    ) -> T:
        spec = self._policy(name.value, idempotent=idempotent)
        timeout, heartbeat = self._timeouts(name)
        attempt = 1
        while True:
            self.attempts[name.value] = self.attempts.get(name.value, 0) + 1
            payload = self._redactor.scrub(arg.model_copy(update={"attempt": attempt}))
            try:
                result = await workflow.execute_activity(
                    name.value,
                    payload,
                    result_type=result_type,
                    start_to_close_timeout=timeout,
                    heartbeat_timeout=heartbeat,
                    retry_policy=ONE_ATTEMPT,
                )
            except ActivityError as exc:
                if isinstance(exc.cause, CancelledError):
                    raise asyncio.CancelledError from exc  # the run was cancelled or interrupted
                info = _error_info(exc)
                if is_non_retryable(info, spec):
                    raise ApplicationError(
                        info.message, type=info.type, non_retryable=True
                    ) from exc
                decision = await workflow.execute_activity(
                    ActivityName.DISPATCH_HOOKS.value,
                    RetryIn(
                        task_id=self.task.id,
                        correlation_id=self.correlation_id,
                        attempt=attempt,
                        activity=name.value,
                        error=info,
                        policy=spec,
                        next_delay=backoff(spec, attempt),
                    ),
                    result_type=RetryOut,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                if decision.abort is not None:
                    raise ApplicationError(
                        decision.abort, type="hook.abort", non_retryable=True
                    ) from exc
                spec = decision.policy
                if attempt >= spec.maximum_attempts:
                    raise ApplicationError(
                        f"{name.value} failed after {attempt} attempt(s): {info.message}",
                        type=info.type,
                        non_retryable=True,
                    ) from exc
                await workflow.sleep(decision.next_delay)
                attempt += 1
                continue
            if result is None:
                return result  # type: ignore[return-value]
            return self._redactor.scrub(result) if hasattr(result, "model_fields") else result  # type: ignore[arg-type]


@workflow.defn(name="RemoteTaskWorkflow")
class RemoteTaskWorkflow:
    """One delegated remote task (R7.3): each turn is a ``run_remote_agent_turn`` activity
    that streams the remote agent's events; the local sub-task record mirrors the remote
    state and the parent is told through ``child_done``. A waiting remote task resumes
    when a reply arrives in this workflow's inbox."""

    def __init__(self) -> None:
        self.task: HarnessTask = HarnessTask(Task())
        self.mailbox: list[Message] = []
        self.remote_task_id: str | None = None
        self.cancel_reason: str | None = None
        self.closed = False

    @workflow.update
    async def inbox(self, message: Message) -> InboxReceipt:
        self.mailbox.append(message)
        return InboxReceipt(
            message_id=message.message_id, accepted=True, state_name=self.task.state_name, cursor=0
        )

    @workflow.signal
    async def cancel(self, reason: str) -> None:
        self.cancel_reason = reason or "cancelled"

    @workflow.query(name="task")
    def task_query(self) -> Task:
        return self.task.proto

    @workflow.run
    async def run(self, start: RemoteStart) -> Task:
        self.task = HarnessTask(start.task)
        self.mailbox = list(start.mailbox)
        outbound = Message(
            message_id=f"{self.task.id}:goal",
            context_id=self.task.context_id,
            role=A2ARole.ROLE_USER,
            parts=[Part(text=start.goal)],
        )
        # This harness is the sender the remote agent sees (it becomes the remote task's
        # reporter); a message that asserts nobody is refused by a tiny-harness peer.
        outbound.metadata.update({"participant_id": start.config.agent})
        self.task = self.task.with_state(TaskState.TASK_STATE_WORKING)
        while True:
            out = await workflow.execute_activity(
                ActivityName.RUN_REMOTE_AGENT_TURN.value,
                RemoteTurnIn(
                    task_id=self.task.id,
                    correlation_id=start.correlation_id,
                    agent=start.agent,
                    message=outbound,
                    remote_task_id=self.remote_task_id,
                ),
                result_type=RemoteTurnOut,
                start_to_close_timeout=start.config.tool_timeout,
                heartbeat_timeout=start.config.heartbeat_timeout,
                retry_policy=ONE_ATTEMPT,
            )
            self.remote_task_id = out.remote_task_id
            state = TaskState.Value(f"TASK_STATE_{out.state_name}")
            self.task = self.task.with_state(state)
            await self._tell_parent(start, out)
            if out.final:
                self.closed = True
                return self.task.proto
            await workflow.wait_condition(
                lambda: bool(self.mailbox) or self.cancel_reason is not None
            )
            if self.cancel_reason is not None:
                self.task = self.task.with_state(TaskState.TASK_STATE_CANCELED)
                self.closed = True
                await self._tell_parent(
                    start, RemoteTurnOut(remote_task_id=out.remote_task_id, state_name="CANCELED")
                )
                return self.task.proto
            reply = self.mailbox.pop(0)
            outbound = Message()
            outbound.CopyFrom(reply)
            outbound.task_id = out.remote_task_id

    async def _tell_parent(self, start: RemoteStart, out: RemoteTurnOut) -> None:
        handle = workflow.get_external_workflow_handle(start.parent_workflow_id)
        with contextlib.suppress(Exception):
            await handle.signal(
                "child_done",
                ChildDone(task_id=self.task.id, state_name=out.state_name, summary=out.text[:500]),
            )


@workflow.defn(name="HeartbeatWorkflow")
class HeartbeatWorkflow:
    """One tick (R16.1-R16.4): poll pull channels, snapshot the inner layer, sweep the
    store. A failing activity fails this run; the schedule fires the next on time."""

    @workflow.run
    async def run(self, tick: HeartbeatTick) -> HeartbeatResult:
        correlation = workflow.info().workflow_id
        polled = await workflow.execute_activity(
            ActivityName.POLL_CHANNELS.value,
            PollIn(task_id="heartbeat", correlation_id=correlation),
            result_type=PollOut,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=ONE_ATTEMPT,
        )
        snapshot = await workflow.execute_activity(
            ActivityName.MONITOR_SNAPSHOT.value,
            MonitorIn(task_id="heartbeat", correlation_id=correlation),
            result_type=MonitorSnapshot,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=ONE_ATTEMPT,
        )
        swept = await workflow.execute_activity(
            ActivityName.RETENTION_SWEEP.value,
            SweepIn(task_id="heartbeat", correlation_id=correlation),
            result_type=SweepOut,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=ONE_ATTEMPT,
        )
        return HeartbeatResult(
            forwarded=polled.forwarded, tasks=len(snapshot.tasks), deleted=swept.deleted
        )


__all__ = [
    "A2A_CONTEXT_ID",
    "A2A_TASK_STATE",
    "TERMINAL",
    "TINY_HARNESS_AGENT",
    "HeartbeatWorkflow",
    "RemoteTaskWorkflow",
    "TaskWorkflow",
    "WorkflowOperations",
    "backoff",
    "state_name",
    "text_message",
]
