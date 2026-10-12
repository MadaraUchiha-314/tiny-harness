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
import hmac
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Final, Literal, cast

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
    from tiny_harness.errors import HookTransportError
    from tiny_harness.harness.channels import (
        CHANNEL_EXT_MEDIA_TYPE,
        ChannelMessage,
        ChannelMessageData,
    )
    from tiny_harness.harness.commands import ChildSnapshot, CommandCall, CommandResult
    from tiny_harness.harness.core import (
        STATUS_EXT_KEY,
        AcceptanceCriterion,
        AgentState,
        CompactionRecord,
        CompletionDecision,
        ContextWindow,
        CoreLoop,
        HarnessTask,
        Lifecycle,
        Participant,
        Role,
        SubState,
        TaskCompleteIn,
        TaskExtensionData,
        TaskRef,
        participant_of,
        state_name,
    )
    from tiny_harness.harness.core.intrinsics import link_subtask
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
        FOLLOW_WINDOW,
        ActivityIn,
        ActivityName,
        AssembleIn,
        ChannelSendIn,
        ChildDone,
        ChildRef,
        CommandIn,
        CommandOut,
        CompactIn,
        CompactOut,
        CompletionIn,
        CompletionOut,
        EmitIn,
        ErrorInfo,
        EventEntry,
        EventPage,
        FollowIn,
        FollowOut,
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
        PushIn,
        RemotePushDelete,
        RemoteResume,
        RemoteStart,
        RemoteTaskIn,
        RemoteTurnIn,
        RemoteTurnOut,
        RemoteWatch,
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
    from tiny_harness.service.inbox import controls_task, is_control

A2A_CONTEXT_ID = SearchAttributeKey.for_keyword("A2AContextId")
A2A_TASK_STATE = SearchAttributeKey.for_keyword("A2ATaskState")
TINY_HARNESS_AGENT = SearchAttributeKey.for_keyword("TinyHarnessAgent")

ONE_ATTEMPT: Final = RetryPolicy(maximum_attempts=1)
EVENT_TAIL: Final = 1000
DEFAULT_TIMEOUT: Final = timedelta(seconds=60)
SHORT_TIMEOUT: Final = timedelta(seconds=30)
FOLLOW_RETRY: Final = timedelta(seconds=5)
"""The pause after a follow activity itself failed, before the next (issue-27 R3)."""
PUSH_RECHECKS: Final = (timedelta(seconds=1), timedelta(seconds=2), timedelta(seconds=4))
"""Delays of the fetches after a push whose claimed state the remote has not yet shown."""
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


def _non_retryable(exc: ActivityError) -> bool:
    return _error_info(exc).non_retryable


def text_message(task: HarnessTask, text: str, *, message_id: str) -> Message:
    return Message(
        message_id=message_id,
        context_id=task.context_id,
        task_id=task.id,
        role=A2ARole.ROLE_AGENT,
        parts=[Part(text=text)],
    )


def sub_task_name(goal: str, index: int) -> str:
    """A ``/sub-task`` child's name: the first line of its description, at most 60
    characters, or ``sub-task <index>`` when it has none."""
    first_line = goal.strip().splitlines()[0] if goal.strip() else f"sub-task {index}"
    return first_line[:60]


def child_extension(
    parent: HarnessTask,
    *,
    name: str,
    goal: str,
    participants: tuple[Participant, ...],
    lifecycle: Lifecycle | None,
    inherit: bool,
    criteria: tuple[AcceptanceCriterion, ...] = (),
) -> TaskExtensionData:
    """A child's extension, linked to ``parent``. A local agent child (``inherit``) copies
    the parent's ``model`` and ``reasoning_effort`` (R7.3); a remote or participant child
    gets neither, as it makes no model call of this harness's."""
    ext = parent.ext
    return TaskExtensionData(
        name=name,
        goal=goal,
        acceptance_criteria=criteria,
        participants=participants,
        parent_tasks=(TaskRef(task_id=parent.id),),
        lifecycle=lifecycle,
        model=ext.model if inherit else None,
        reasoning_effort=ext.reasoning_effort if inherit else None,
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

    async def drain(self, task: HarnessTask, state: AgentState) -> tuple[HarnessTask, AgentState]:
        state, _ = await self._wf.drain(task, state)
        return self._wf.task, state  # a task envelope may have changed the extension

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

    async def await_next_message(self, task: HarnessTask, text: str) -> HarnessTask:
        return await self._wf.set_status(
            task,
            TaskState.TASK_STATE_INPUT_REQUIRED,
            text=text,
            sub_state=SubState.AWAITING_NEXT_MESSAGE,
            persist=True,
        )

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
        self.history_notes: list[str] = []
        self.command_run: asyncio.Task[None] | None = None  # a command a cut turn left running
        self.unanswered = False  # an accepted message no finished turn has answered yet
        self.attempts: dict[str, int] = {}
        self.cancel_reason: str | None = None
        self.interrupted = False
        self.closed = False
        self.turns_this_run = 0
        self.last_refusal = ""
        self.handled = 0  # commands and controls consumed since the last wake
        self.completion_by: str | None = None  # a participant's accepted control complete
        self.fresh_run = False
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
        # A message may ask for an interrupt, never cancel one already asked for, such as
        # a completion's (critic A3); the wake clears it once nothing runs.
        if (
            message.HasField("metadata")
            and "interrupt" in message.metadata.fields
            and message.metadata.fields["interrupt"].bool_value
        ):
            self.interrupted = True
        if is_control(message):  # authorized by the validator: cut the turn (R5.2)
            self.interrupted = True
        return InboxReceipt(
            message_id=mid, accepted=True, state_name=self.task.state_name, cursor=self.next_seq
        )

    @inbox.validator
    def _inbox_validator(self, message: Message) -> None:
        """Runs before the handler: a refused control never interrupts a turn (abuse
        case 4). The sender must be on the task in a role other than ``watcher``."""
        if self.closed:
            raise ValueError("task is closed")
        if not is_control(message):
            return
        sender = participant_of(message)
        if sender is None:
            raise ValueError("no participant asserted")
        if not self.task.ext.is_participant(sender):
            raise ValueError("not a participant")
        if not controls_task(self.task.ext, sender):
            raise ValueError("a watcher cannot complete the task")

    @workflow.signal
    async def cancel(self, reason: str) -> None:
        self.cancel_reason = reason or "cancelled"

    @workflow.signal
    async def child_done(self, done: ChildDone) -> None:
        """A child's state change; terminal states resolve it (R7.3). Every change
        updates the child's row, which the parent shows on its own stream once idle
        (issue-25 R5.6); only an ending, or a remote child parking with something to say,
        becomes a note for the model, so a child resuming never wakes it (issue-27 R2.7)."""
        terminal = done.state_name in TERMINAL_NAMES
        interrupted = done.state_name in ("INPUT_REQUIRED", "AUTH_REQUIRED")
        remote = False
        for i, child in enumerate(self.children):
            if child.task_id == done.task_id:
                remote = child.kind == "remote"
                self.children[i] = child.model_copy(
                    update={
                        "done": terminal,
                        "state_name": done.state_name,
                        "sub_state": done.sub_state,
                        "summary": done.summary,
                    }
                )
        if terminal or (remote and interrupted):
            note = f"Sub-task {done.task_id} is {done.state_name}: {done.summary}"
            self.notes.append(note.strip())

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
        if (
            not self.mailbox
            and self.task.state == TaskState.TASK_STATE_SUBMITTED
            and self.task.lifecycle == "conversation"
        ):
            # A /sub-task starts without a first message: it waits for one (R9.2).
            self.task = await self.set_status(
                self.task,
                TaskState.TASK_STATE_INPUT_REQUIRED,
                sub_state=SubState.AWAITING_NEXT_MESSAGE,
                persist=True,
            )
        loop = CoreLoop(WorkflowOperations(self), max_turns=start.config.max_turns)
        while True:
            await workflow.wait_condition(lambda: self._ready() or self._rows() is not None)
            if self.cancel_reason is not None:
                return await self._finish(TaskState.TASK_STATE_CANCELED, text=self.cancel_reason)
            await self._show_sub_tasks()
            if not self._ready():
                continue
            # No turn runs here, so an interrupt has nothing to cut; one that arrives from
            # now on cuts the turn this wake starts.
            self.interrupted = False
            self.handled, self.last_refusal = 0, ""
            # Roll over before intake, so a rollover carries the messages still in the
            # mailbox and the new run wakes for them (R19.8).
            await self.maybe_continue_as_new(self.task, self._fold_history_notes(self.state))
            self.turns_this_run += 1
            # Intake before the loop (issue-25 R6.2): commands and controls are consumed
            # here, and only ordinary messages or the notes start a turn.
            self.state, accepted = await self._dispatch(self.state)
            if self.completion_by is not None:
                done = await self._complete()
                if done is not None:
                    return done
                if accepted == 0 and not self.notes and not self.unanswered:
                    continue
                # A message taken in the same intake still gets its turn (critic A2).
            elif accepted == 0 and not self.notes and not self.unanswered:
                if self.last_refusal and self.handled == 0:
                    # The sender is a participant (strangers never reach the workflow), so
                    # the stream they opened ends with the unchanged state and the reason;
                    # a refused message never wakes the model (abuse case 4).
                    await self._re_emit(text=f"message not accepted: {self.last_refusal}")
                continue
            self.fresh_run = True  # its first drain must not roll over what was accepted
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
            self.unanswered = False  # the finished turn saw every accepted message
            if outcome.kind in ("waiting_for_reply", "waiting_for_children", "waiting_for_message"):
                continue
            return await self._finish(None)

    def _ready(self) -> bool:
        return (
            bool(self.mailbox)
            or bool(self.notes)
            or self.cancel_reason is not None
            or self.completion_by is not None
            # A cut turn may have taken a message into the history (critic A1): answer it.
            or self.unanswered
        )

    def _rows(self) -> HarnessTask | None:
        """The task with each sub-task row showing its child's last state; ``None`` when
        every row already does."""
        children = {c.task_id: c for c in self.children}
        refs: list[TaskRef] = []
        for ref in self.task.ext.sub_tasks:
            child = children.get(ref.task_id)
            if child is not None and (ref.state, ref.sub_state) != (
                child.state_name,
                child.sub_state,
            ):
                ref = ref.model_copy(
                    update={"state": child.state_name, "sub_state": child.sub_state}
                )
            refs.append(ref)
        if tuple(refs) == self.task.ext.sub_tasks:
            return None
        return self.task.with_ext(self.task.ext.model_copy(update={"sub_tasks": tuple(refs)}))

    async def _show_sub_tasks(self) -> None:
        """Log the task with its sub-task rows current (issue-25 R5.6), so a client
        following the parent sees them change without following each child.

        Only while nothing waits on an answer: the ``Task`` event repeats the parent's
        state, and a parked one (``INPUT_REQUIRED``) logged after a message was taken
        but before the turn that answers it would end that message's stream. With no
        message pending, the next message's stream starts after it."""
        if self.mailbox or self.unanswered or self.completion_by is not None:
            return
        updated = self._rows()
        if updated is None:
            return
        self.task = updated
        entry = self._emit(updated.proto)
        await self.persist(None)
        await self._deliver(entry)

    def waiting_for_reply(self) -> bool:
        return self.pending_help is not None

    async def drain(self, task: HarnessTask, state: AgentState) -> tuple[AgentState, int]:
        """Top of a turn (R15.3): roll over if due, fold notes into the history, then
        dispatch the mailbox; returns how many ordinary messages intake accepted."""
        self.task = task
        state = self._fold_history_notes(state)
        if self.fresh_run:
            self.fresh_run = False
        else:
            await self.maybe_continue_as_new(task, state)
        self.turns_this_run += 1
        for note in self.take_notes():  # sub-task and remote-agent results: data, not orders
            state = state.append(MessageItem(role=MessageRole.USER, text=note, source="agent"))
        return await self._dispatch(state)

    async def _dispatch(self, state: AgentState) -> tuple[AgentState, int]:
        """Intake every pending message (issue-25 R6.2): a command runs and replies, a
        control is noted for ``_complete``, a refusal keeps its reason in
        ``last_refusal``, and only an ordinary accepted message joins the history.
        Returns the history and how many ordinary messages it gained."""
        accepted = 0
        while self.mailbox:
            out = await self._classify()
            if out is None:
                state = self._fold_history_notes(state)
                continue
            accepted += 1
            self.unanswered = True
            if out.task is not None:  # a task envelope changed the extension (R15.1)
                self.task = HarnessTask(out.task)
                self._emit(self.task.proto)
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

    def _fold_history_notes(self, state: AgentState) -> AgentState:
        """Add pending history notes (a participant's /sub-task, R9) to ``state`` without
        starting a turn. Called after every intake and before every rollover, so a note
        is never lost to continue-as-new (critic A4)."""
        for note in self.history_notes:
            state = state.append(MessageItem(role=MessageRole.USER, text=note, source="agent"))
        self.history_notes = []
        self.state = state
        return state

    async def _classify(self) -> IntakeOut | None:
        """Intake the oldest mailbox message; consume it when it is refused, a command or
        a control, else return it. The message leaves the mailbox only once its intake
        has completed: an interrupt or a cancel during intake leaves it for the next
        dispatch (R15.5)."""
        out = await self.call(
            ActivityName.INTAKE,
            IntakeIn(
                task_id=self.task.id,
                correlation_id=self.correlation_id,
                task=self.task.proto,
                message=self.mailbox[0],
                surfaces=self.surfaces,
            ),
            IntakeOut,
        )
        self.mailbox.pop(0)
        if not out.accepted:
            self.last_refusal = out.reason or "not accepted"
            return None
        if out.command is not None:
            self.handled += 1
            # Shielded: cutting the turn this intake runs in must not cut the command, whose
            # message is already consumed; ``_await_runner`` lets it finish (critic A1).
            run = asyncio.create_task(self._run_command(out.command, out.participant_id or ""))
            self.command_run = run
            await asyncio.shield(run)
            self.command_run = None
            return None
        if out.control is not None:
            self.handled += 1
            self.completion_by = out.participant_id or ""
            return None
        return out

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
        if self.command_run is not None:  # finish the command the cut interrupted (A1)
            await self.command_run
            self.command_run = None
        return False

    async def _run_participant(self) -> Task:
        """A task assigned to a human: the assignee's ordinary message completes it
        (R12.3). Commands and controls are dispatched first, so ``/status`` is never
        taken for the answer (issue-25 R3.4)."""
        assignee = next((p.id for p in self.task.ext.participants if p.role is Role.ASSIGNEE), None)
        if self.task.state != TaskState.TASK_STATE_INPUT_REQUIRED:
            self.task = await self.set_status(
                self.task, TaskState.TASK_STATE_INPUT_REQUIRED, text=self.task.ext.goal
            )
        while True:
            await workflow.wait_condition(
                lambda: (
                    bool(self.mailbox)
                    or self.cancel_reason is not None
                    or self.completion_by is not None
                )
            )
            if self.cancel_reason is not None:
                return await self._finish(TaskState.TASK_STATE_CANCELED, text=self.cancel_reason)
            out = await self._classify() if self.mailbox else None
            if self.completion_by is not None:
                done = await self._complete()
                if done is not None:
                    return done
                continue
            if out is None or (assignee is not None and out.participant_id != assignee):
                continue
            self.state = self.state.append(MessageItem(role=MessageRole.USER, text=out.text))
            return await self._finish(TaskState.TASK_STATE_COMPLETED, text=out.text)

    async def _complete(self) -> Task | None:
        """A participant's control complete (R5.2, R5.4): ``task.complete.in`` decides,
        told who asked. COMPLETE finishes the task for every subscriber; otherwise the
        refusal names what is open and the task waits for the next message."""
        actor = self.completion_by or ""
        self.completion_by = None
        unresolved = self.unresolved()
        out = await self.call(
            ActivityName.DECIDE_COMPLETION,
            CompletionIn(
                task_id=self.task.id,
                correlation_id=self.correlation_id,
                task=self.task.proto,
                unresolved=unresolved,
                requested_by=actor,
            ),
            CompletionOut,
        )
        if out.result == "complete":
            return await self._finish(TaskState.TASK_STATE_COMPLETED, text=f"completed by {actor}")
        if out.result == "wait":
            names = ", ".join(r.task_id for r in unresolved)
            reason = f"unresolved sub-tasks: {names}"
        else:
            reason = out.reason or "refused by a hook"
        workflow.logger.info("completion.refused", extra={"task_id": self.task.id})
        # A cut turn left the task WORKING with nothing running: it waits for the next
        # message, as a turn's end would leave it.
        state, sub_state = self.task.state, self.task.sub_state
        if state != TaskState.TASK_STATE_INPUT_REQUIRED:
            state, sub_state = TaskState.TASK_STATE_INPUT_REQUIRED, SubState.AWAITING_NEXT_MESSAGE
        self.task = await self.set_status(
            self.task,
            state,
            text=f"completion refused: {reason}",
            sub_state=sub_state,
            persist=True,
        )
        return None

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
            # A conversation sub-task (/sub-task) may outlive its parent: a closed parent
            # has no one to tell, and must not fail the child (issue-25 R9.2).
            with contextlib.suppress(ApplicationError):
                await handle.signal(
                    "child_done",
                    ChildDone(
                        task_id=self.task.id,
                        state_name=self.task.state_name,
                        summary=summary[:500],
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
        self.unanswered = start.unanswered
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
                "unanswered": self.unanswered,
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
        sub_state: SubState | None = None,
        persist: bool = False,
        snapshot: bool = False,
    ) -> HarnessTask:
        """Move the task to ``state`` and log the update. ``sub_state`` is written to both
        documented places, ``Task.metadata`` and the status update's metadata (R4.1);
        without one, a stale sub-state is cleared (R3.3). ``persist`` stores the new state
        before anyone can see it (R3.6): a parked task is idle, so a client that reacts
        to the update never finds the store write still in flight. ``snapshot`` also logs
        the updated ``Task`` right after the update, in the same activation, so the two
        reach a stream together and the snapshot is its last event."""
        status = TaskStatus(state=state, timestamp=workflow.now())  # type: ignore[arg-type]
        if message is None and text:
            message = text_message(task, text, message_id=f"{task.id}:status:{self.next_seq}")
        if message is not None:
            status.message.CopyFrom(message)
        updated = task.with_state(state, sub_state)
        updated.proto.status.CopyFrom(status)
        if persist:
            await self.persist(None, task=updated)
        event = TaskStatusUpdateEvent(task_id=task.id, context_id=task.context_id, status=status)
        if sub_state is not None:
            event.metadata.fields[STATUS_EXT_KEY].CopyFrom(
                updated.proto.metadata.fields[STATUS_EXT_KEY]
            )
        entry = self._emit(event)
        if snapshot:
            self._emit(updated.proto)
        if self.start.config.search_attributes:
            workflow.upsert_search_attributes(  # pyright: ignore[reportUnknownMemberType]
                [A2A_TASK_STATE.value_set(updated.state_name)]
            )
        await self._deliver(entry)
        self.task = updated  # visible to the ``task`` query once its I/O is done
        if self.start.parent_workflow_id and not updated.is_terminal:
            await self._tell_parent(updated)  # a terminal state is told by ``_finish``
        return updated

    async def _tell_parent(self, task: HarnessTask) -> None:
        """A sub-task tells its parent each state change, so the parent's row for it stays
        current (issue-25 R5.6). A parent that has closed has no row to update."""
        handle = workflow.get_external_workflow_handle(self.start.parent_workflow_id or "")
        with contextlib.suppress(ApplicationError):
            await handle.signal(
                "child_done",
                ChildDone(task_id=task.id, state_name=task.state_name, sub_state=task.sub_state),
            )

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
        return await self.set_status(
            task,
            TaskState.TASK_STATE_INPUT_REQUIRED,
            message=message,
            sub_state=SubState.AWAITING_ANSWER,
            persist=True,
        )

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

    async def persist(
        self,
        compaction: CompactionRecord | None,
        *,
        final: bool = False,
        task: HarnessTask | None = None,
    ) -> None:
        current = task or self.task
        await self.call(
            ActivityName.PERSIST,
            PersistIn(
                task_id=current.id,
                correlation_id=self.correlation_id,
                task=current.proto,
                state=self.state,
                compaction=compaction,
                events=tuple(self.events) if final else (),
                final=final,
            ),
            type(None),
        )

    # --- commands (issue-25 R6, R9) ----------------------------------------------------

    async def _run_command(self, call: CommandCall, sender: str) -> None:
        """Run ``call`` through the ``run_command`` activity, then apply its intents in
        order: settings, spawn, reply. The task's state does not change (R6.2, R10.2)."""
        children = tuple(
            ChildSnapshot(task_id=c.task_id, state=c.state_name) for c in self.children
        )
        try:
            out = await self.call(
                ActivityName.RUN_COMMAND,
                CommandIn(
                    task_id=self.task.id,
                    correlation_id=self.correlation_id,
                    call=call,
                    sender=sender,
                    task=self.task.proto,
                    children=children,
                ),
                CommandOut,
            )
            result = out.result
        except ApplicationError as exc:  # a remote executor failed (R6a.9)
            detail = "hook transport" if exc.type == HookTransportError.code else exc.message
            result = CommandResult(reply=f"/{call.name} failed: {detail}")
        changed = False
        if result.settings is not None:
            settings = {
                "model": result.settings.model,
                "reasoning_effort": result.settings.reasoning_effort,
            }
            update = {k: v for k, v in settings.items() if v is not None}
            if update:
                self.task = self.task.with_ext(self.task.ext.model_copy(update=update))
                changed = True
        ref: TaskRef | None = None
        if result.spawn is not None:
            ref = await self.spawn_sub_task(self.task, result.spawn.goal, sender)
            changed = True
            # The agent normally creates its own sub-tasks; one a participant created is
            # noted in the history, so its later updates do not arrive unexplained. It is
            # a history note, not a wake-up note: ``_dispatch`` adds it to the history
            # without starting a turn, and the name is quoted data (abuse case 5).
            name = json.dumps(sub_task_name(result.spawn.goal, len(self.children)))
            self.history_notes.append(
                f"Participant {sender} created sub-task {ref.task_id} ({name}); "
                "its updates will arrive here."
            )
        if changed:  # R7.3, R8.3, R9.1: stored before the reply is seen
            await self.persist(None)
        reply = result.reply
        metadata: dict[str, str] = {"command": call.name}
        if ref is not None:
            # The handler ran before the child existed: the id is the workflow's own line,
            # concatenated, never a template the reply could inject into (R9.1, R9.4).
            reply = (reply + "\n" if reply else "") + f"Created sub-task {ref.task_id}."
            metadata["task_ref"] = ref.task_id
        message = text_message(
            self.task, reply, message_id=f"{self.task.id}:command:{self.next_seq}"
        )
        message.metadata.update(metadata)
        # A changed task is published as a Task snapshot after the reply, never before it:
        # a stream ends at the newest INPUT_REQUIRED event, and a snapshot logged while
        # the reply is still to come would end the sender's stream without it.
        await self._re_emit(message=message, snapshot=changed)

    async def _re_emit(
        self, *, text: str | None = None, message: Message | None = None, snapshot: bool = False
    ) -> None:
        """Re-emit the current state with ``text`` or ``message``, so the sender's stream
        ends cleanly. A task that never started (a first message that was a command or
        was refused) parks as a conversation awaiting the next message."""
        state, sub_state, persist = self.task.state, self.task.sub_state, False
        if state == TaskState.TASK_STATE_SUBMITTED:
            state = TaskState.TASK_STATE_INPUT_REQUIRED
            sub_state, persist = SubState.AWAITING_NEXT_MESSAGE, True
        await self.set_status(
            self.task,
            state,
            text=text,
            message=message,
            sub_state=sub_state,
            persist=persist,
            snapshot=snapshot,
        )

    # --- children ------------------------------------------------------------------

    async def spawn_child(self, task: HarnessTask, command: WorkflowCommand) -> TaskRef:
        """An agent's ``spawn_subtask`` (a delegated child, local or remote) or
        ``create_task_for_participant`` (a participant task) (R3.4, R7.3)."""
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
        raw_step = payload.get("step")
        step = str(raw_step) if raw_step else None
        participants = task.ext.participants
        agent = payload.get("agent")
        if command.kind == "create_participant_task":
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
            ext = child_extension(
                task,
                name=name,
                goal=goal,
                criteria=criteria,
                participants=participants,
                lifecycle=None,
                inherit=False,
            )
            child = HarnessTask.new(child_id, task.context_id, ext)
            await self._start_local_child(child, mode="participant", mailbox=(), step=step)
            return TaskRef(task_id=child_id)
        if not participants:
            participants = (
                Participant(id=self.start.config.agent, kind="agent", role=Role.ASSIGNEE),
            )
        elif not agent and not any(p.id == self.start.config.agent for p in participants):
            # The goal message is sent as this agent, and intake accepts only a participant:
            # without this a refused goal would leave the child idle (issue-25 R6.2).
            participants = (
                *participants,
                Participant(id=self.start.config.agent, kind="agent", role=Role.REPORTER),
            )
        ext = child_extension(
            task,
            name=name,
            goal=goal,
            criteria=criteria,
            participants=participants,
            lifecycle="delegated",
            inherit=not agent,  # a remote child runs on the remote agent's model
        )
        child = HarnessTask.new(child_id, task.context_id, ext)
        if agent:
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
                ChildRef(task_id=child_id, workflow_id=child_id, kind="remote", step=step)
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
        await self._start_local_child(child, mode="agent", mailbox=(first,), step=step)
        return TaskRef(task_id=child_id)

    async def spawn_sub_task(self, task: HarnessTask, goal: str, reporter: str) -> TaskRef:
        """``/sub-task`` (R9.1, R9.2): a conversation child in the same context with the
        sender as its reporter and this agent as its assignee, inheriting the parent's
        settings (R7.3). It starts without a first message and waits in
        ``INPUT_REQUIRED(awaiting-next-message)``. The child is linked into ``self.task``;
        the caller emits the ``Task`` event and persists."""
        index = len(self.children) + 1
        child_id = f"{task.id}.{index}"
        sender = task.ext.participant(reporter)
        participants = (
            Participant(id=reporter, kind=sender.kind if sender else "human", role=Role.REPORTER),
            Participant(id=self.start.config.agent, kind="agent", role=Role.ASSIGNEE),
        )
        ext = child_extension(
            task,
            name=sub_task_name(goal, index),
            goal=goal,
            participants=participants,
            lifecycle="conversation",
            inherit=True,
        )
        child = HarnessTask.new(child_id, task.context_id, ext)
        await self._start_local_child(child, mode="agent", mailbox=(), step=None)
        ref = TaskRef(task_id=child_id)
        self.task = link_subtask(task, ref, None)
        return ref

    async def _start_local_child(
        self,
        child: HarnessTask,
        *,
        mode: Literal["agent", "participant"],
        mailbox: tuple[Message, ...],
        step: str | None,
    ) -> None:
        start = TaskStart(
            task=child.proto,
            state=AgentState(task_id=child.id),
            mode=mode,
            config=self.start.config,
            correlation_id=self.correlation_id,
            mailbox=mailbox,
            parent_workflow_id=workflow.info().workflow_id,
        )
        await workflow.start_child_workflow(
            "TaskWorkflow",
            start,
            id=child.id,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        self.children.append(
            ChildRef(
                task_id=child.id,
                workflow_id=child.id,
                kind="participant" if mode == "participant" else "local",
                step=step,
            )
        )

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
    when a reply arrives in this workflow's inbox.

    While the remote task is parked, the stand-in watches it (issue-27): by push, where
    the remote agent calls ``POST /a2a/push/<id>`` and the ``remote_push`` update wakes
    this workflow to fetch the task, or by following it with ``SubscribeToTask``. A
    change is relayed to the parent as a turn's end is."""

    def __init__(self) -> None:
        self.task: HarnessTask = HarnessTask(Task())
        self.start: RemoteStart | None = None
        self.mailbox: list[Message] = []
        self.remote_task_id: str | None = None
        self.cancel_reason: str | None = None
        self.closed = False
        self.watch: RemoteWatch | None = None
        self.push_pending = False
        self.claimed = ""  # the state the last push claimed, while a fetch disagrees
        self.recheck: int | None = None  # the next PUSH_RECHECKS delay, if one is due
        self.last = RemoteTurnOut(remote_task_id="", state_name="SUBMITTED")

    @workflow.update
    async def inbox(self, message: Message) -> InboxReceipt:
        self.mailbox.append(message)
        return InboxReceipt(
            message_id=message.message_id, accepted=True, state_name=self.task.state_name, cursor=0
        )

    @workflow.update
    async def remote_push(self, push: PushIn) -> None:
        """A verified push (R2.2): a doorbell only. The state comes from ``GetTask``; the
        state the body claims only says whether to fetch again (R2.3)."""
        self.push_pending = True
        self.claimed = push.claimed_state
        self.recheck = None

    @remote_push.validator
    def _check_push(self, push: PushIn) -> None:
        """Refuse before anything is recorded (abuse cases 1-4): a rejected update writes no
        history. One message for every reason, and a constant-time digest comparison."""
        watch = self.watch
        accepted = (
            not self.closed
            and watch is not None
            and watch.mode == "push"
            and hmac.compare_digest(push.token_digest.encode(), watch.token_digest.encode())
            and push.remote_task_id == self.remote_task_id
        )
        if not accepted:
            raise ValueError("push not accepted")

    @workflow.signal
    async def cancel(self, reason: str) -> None:
        self.cancel_reason = reason or "cancelled"

    @workflow.query(name="task")
    def task_query(self) -> Task:
        return self.task.proto

    @workflow.run
    async def run(self, start: RemoteStart) -> Task:
        self.start = start
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
        resumed = start.resume
        if resumed is not None:  # a continued run: the remote task is parked, watch it
            self.remote_task_id = resumed.remote_task_id
            self.watch = resumed.watch
            self.last = resumed.last
            self.push_pending = resumed.watch.mode == "push"  # reconcile across the gap
        else:
            self.task = self.task.with_state(TaskState.TASK_STATE_WORKING)
        while True:
            if resumed is None:
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
                await self._apply(out, always=True)
                if out.final:
                    return await self._end()
            resumed = None
            parked = await self._park()
            self.recheck, self.claimed = None, ""  # a recheck belongs to one park only
            if parked == "ended":
                return await self._end()
            if parked == "roll":
                workflow.continue_as_new(self._resume())
            if self.cancel_reason is not None:
                self.task = self.task.with_state(TaskState.TASK_STATE_CANCELED)
                await self._tell_parent(
                    RemoteTurnOut(remote_task_id=self.remote_task_id or "", state_name="CANCELED")
                )
                return await self._end()
            reply = self.mailbox.pop(0)
            outbound = Message()
            outbound.CopyFrom(reply)
            outbound.task_id = self.remote_task_id or ""

    def _resume(self) -> RemoteStart:
        """The next run's input: the same stand-in, still parked (history bound, R19.8)."""
        assert self.start is not None and self.watch is not None
        return self.start.model_copy(
            update={
                "task": self.task.proto,
                "mailbox": tuple(self.mailbox),
                "resume": RemoteResume(
                    remote_task_id=self.remote_task_id or "", watch=self.watch, last=self.last
                ),
            }
        )

    def _remote_in(self) -> RemoteTaskIn:
        assert self.start is not None and self.remote_task_id is not None
        return RemoteTaskIn(
            task_id=self.task.id,
            correlation_id=self.start.correlation_id,
            agent=self.start.agent,
            remote_task_id=self.remote_task_id,
            participant=self.start.config.agent,
            known_text=self.last.text,
        )

    def _history_full(self) -> bool:
        assert self.start is not None
        info = workflow.info()
        over = info.get_current_history_length() > self.start.config.history_event_bound
        return over or info.is_continue_as_new_suggested()

    async def _park(self) -> Literal["interrupted", "ended", "roll"]:
        """Watch the parked remote task until a reply or a cancel arrives, the remote task
        ends, or the history is due to roll over."""
        assert self.start is not None
        watch = self.watch
        if watch is None:
            if not self.remote_task_id:
                watch = RemoteWatch(mode="off")  # nothing to watch without its id
            else:
                try:
                    watch = await workflow.execute_activity(
                        ActivityName.REGISTER_REMOTE_PUSH.value,
                        self._remote_in(),
                        result_type=RemoteWatch,
                        start_to_close_timeout=SHORT_TIMEOUT,
                        retry_policy=ONE_ATTEMPT,
                    )
                except ActivityError:
                    watch = RemoteWatch(mode="follow")
            self.watch = watch
            # Fetch once: a change between the turn's end and the registration (R1.4).
            self.push_pending = watch.mode == "push"
        while True:
            if self._history_full():
                return "roll"
            follow: workflow.ActivityHandle[FollowOut] | None = None
            if watch.mode == "follow":
                follow = workflow.start_activity(
                    ActivityName.FOLLOW_REMOTE_TASK.value,
                    FollowIn(**self._remote_in().model_dump(), known_state=self.last.state_name),
                    result_type=FollowOut,
                    start_to_close_timeout=FOLLOW_WINDOW + timedelta(minutes=1),
                    heartbeat_timeout=self.start.config.heartbeat_timeout,
                    retry_policy=ONE_ATTEMPT,
                )
            try:
                await workflow.wait_condition(
                    self._woken(follow),
                    timeout=PUSH_RECHECKS[self.recheck] if self.recheck is not None else None,
                )
            except TimeoutError:
                assert self.recheck is not None
                self.recheck += 1
                self.push_pending = True  # fetch again: the push outran the remote's record
            if self._interrupted():
                if follow is not None and not follow.done():
                    follow.cancel()  # a reply or a cancel goes first (R3.4)
                    with contextlib.suppress(ActivityError, asyncio.CancelledError):
                        await follow
                return "interrupted"
            if self.push_pending:
                self.push_pending = False
                try:
                    out = await workflow.execute_activity(
                        ActivityName.GET_REMOTE_TASK.value,
                        self._remote_in(),
                        result_type=RemoteTurnOut,
                        start_to_close_timeout=SHORT_TIMEOUT,
                        # One call per fetch: the rechecks are the retries (abuse case 6).
                        retry_policy=ONE_ATTEMPT,
                    )
                except ActivityError:
                    continue  # keep the last state (fail closed); the next push tries again
                if await self._apply(out) and out.final:
                    return "ended"
                self._schedule_recheck(out)
                continue
            assert follow is not None
            try:
                followed = await follow
            except ActivityError as exc:
                if _non_retryable(exc):
                    # The agent is gone or not a remote one: following again cannot help.
                    workflow.logger.warning("stopped following: %s", exc.message)
                    watch = self.watch = RemoteWatch(mode="off")
                    continue
                # The follow died (a worker restart, a heartbeat timeout): pause, then again.
                await self._pause()
                continue
            out = followed.out
            if not followed.changed or out is None:
                continue  # the window ended quietly; follow again
            if not await self._apply(out):
                await self._pause()  # a "change" that is not one must never spin the loop
                continue
            if out.final:
                return "ended"

    async def _pause(self) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await workflow.wait_condition(self._interrupted, timeout=FOLLOW_RETRY)

    def _schedule_recheck(self, out: RemoteTurnOut) -> None:
        """A remote agent may push before its own ``GetTask`` shows the change: while the
        fetched state differs from the claimed one, fetch again, at most
        ``len(PUSH_RECHECKS)`` more times (R2.3, abuse case 6)."""
        if self.claimed and out.state_name != self.claimed:
            due = 0 if self.recheck is None else self.recheck
            self.recheck = due if due < len(PUSH_RECHECKS) else None
        else:
            self.recheck = None
        if self.recheck is None:
            self.claimed = ""

    def _woken(self, follow: workflow.ActivityHandle[FollowOut] | None) -> Callable[[], bool]:
        return lambda: (
            self._interrupted() or self.push_pending or (follow is not None and follow.done())
        )

    def _interrupted(self) -> bool:
        return bool(self.mailbox) or self.cancel_reason is not None

    async def _apply(self, out: RemoteTurnOut, *, always: bool = False) -> bool:
        """Record ``out`` and tell the parent when it differs from the last (R2.4)."""
        changed = (out.state_name, out.text) != (self.last.state_name, self.last.text)
        if not (changed or always):
            return False
        self.last = out
        self.task = self.task.with_state(TaskState.Value(f"TASK_STATE_{out.state_name}"))
        await self._tell_parent(out)
        return True

    async def _end(self) -> Task:
        """Every exit: refuse later pushes, then remove the push config (R5)."""
        self.closed = True
        watch = self.watch
        if watch is not None and watch.mode == "push" and self.start is not None:
            try:
                await workflow.execute_activity(
                    ActivityName.DELETE_REMOTE_PUSH.value,
                    RemotePushDelete(**self._remote_in().model_dump(), config_id=watch.config_id),
                    start_to_close_timeout=SHORT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except ActivityError as exc:  # the state reached stands (R5.2)
                workflow.logger.warning("push config cleanup failed: %s", exc.message)
        return self.task.proto

    async def _tell_parent(self, out: RemoteTurnOut) -> None:
        assert self.start is not None
        handle = workflow.get_external_workflow_handle(self.start.parent_workflow_id)
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
    "child_extension",
    "state_name",
    "text_message",
]
