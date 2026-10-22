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
from collections.abc import Callable, Sequence
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
    from tiny_harness.harness.agents import SELF_AGENT_ID
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
    from tiny_harness.harness.media import MediaAttachment, MediaKind, MediaRef
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
        OpenSpeechIn,
        OpenSpeechOut,
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
        SpeakIn,
        SpeechJob,
        StartAgentTaskIn,
        SweepIn,
        SweepOut,
        TaskMonitor,
        TaskStart,
        ToolIn,
        ToolOut,
        TranscribeIn,
        TranscribeOut,
        TriggerIn,
        TriggerOut,
        event_entry,
    )
    from tiny_harness.service.inbox import EVENT_MEDIA_TYPE, controls_task, is_control

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
SPEECH_UNAVAILABLE: Final = "speech unavailable"
"""The status note when a spoken reply fails or is stopped (issue-38 R4.5)."""
TRANSCRIPTION_FAILED: Final = "(transcription failed)"
"""The transcript of audio speech-to-text refused (issue-38 error handling)."""
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


SUB_TASK_RESULT_CAP: Final = 4_000
"""How much of a sub-task's last answer reaches its parent: room for a result, which is
why a sub-task runs in isolation (issue-34 R7.3); a longer one is cut and marked."""


def sub_task_result(text: str) -> str:
    """A finished sub-task's answer as its parent hears it, at most the cap."""
    if len(text) <= SUB_TASK_RESULT_CAP:
        return text
    return text[: SUB_TASK_RESULT_CAP - 1] + "…"


def sub_task_brief(goal: str, description: str, criteria: Sequence[str]) -> str:
    """The message a remote agent is given: the goal, the context and each acceptance
    criterion, since it sees nothing else of this task (issue-34 R7.2)."""
    parts = [goal]
    if description:
        parts.append(description)
    if criteria:
        parts.append("Acceptance criteria:\n" + "\n".join(f"- {c}" for c in criteria))
    return "\n\n".join(parts)


def brief_message(
    child_id: str, context_id: str, *, sender: str, text: str, envelope: JsonObject | None
) -> Message:
    """The first message of a child task on an agent (issue-34 R7.2): the brief as text,
    and as a task envelope that a callee with the task extension creates the task from.
    ``text`` empty: the child starts without a message for its model (``/sub-task``)."""
    parts: list[Part] = [Part(text=text)] if text else []
    if envelope is not None:
        value = struct_pb2.Value()
        value.struct_value.update({"kind": "task", "payload": envelope})
        parts.append(Part(data=value, media_type=EVENT_MEDIA_TYPE))
    message = Message(
        message_id=f"{child_id}:brief", context_id=context_id, role=A2ARole.ROLE_USER, parts=parts
    )
    message.metadata.update({"participant_id": sender})
    return message


def child_extension(
    parent: HarnessTask,
    *,
    name: str,
    goal: str,
    participants: tuple[Participant, ...],
    lifecycle: Lifecycle | None,
    inherit: bool,
    criteria: tuple[AcceptanceCriterion, ...] = (),
    description: str = "",
) -> TaskExtensionData:
    """A child's extension, linked to ``parent``. A local agent child (``inherit``) copies
    the parent's ``model`` and ``reasoning_effort`` (R7.3); a remote or participant child
    gets neither, as it makes no model call of this harness's."""
    ext = parent.ext
    return TaskExtensionData(
        name=name,
        goal=goal,
        description=description,
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
        await self._wf.note_unseen(turn.unseen)
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
        if isinstance(out.result, ToolResult):
            await self._wf.show_media(task, out.result, out.urls)
        return out.result

    async def decide_completion(self, task: HarnessTask) -> TaskCompleteIn:
        unresolved = self._wf.unresolved()
        if not unresolved and self._wf.notes:
            # A sub-task ended during this turn: its result is the reason it ran, so the
            # model reads it in one more turn before the task may end (issue-34 R7.5).
            return TaskCompleteIn(
                task_id=task.id,
                correlation_id=self._wf.correlation_id,
                unresolved=unresolved,
                result=CompletionDecision.WAIT,
                reason="a sub-task's result is still to be read",
            )
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
        updated = await self._wf.set_status(task, state)
        if state == TaskState.TASK_STATE_WORKING:
            await self._wf.flush_notes()  # notes held while a message waited for its turn
        return updated

    async def wait_for_reply(self, task: HarnessTask, help: JsonObject) -> HarnessTask:
        return await self._wf.ask(task, help)

    async def await_next_message(self, task: HarnessTask, text: str) -> HarnessTask:
        # The speech artifact goes before the reply's final status: a stream ends there
        # (issue-38 design critic 1); the speech job starts once the reply is shown.
        speech = await self._wf.open_speech(task, text)
        try:
            return await self._wf.set_status(
                task,
                TaskState.TASK_STATE_INPUT_REQUIRED,
                text=text,
                sub_state=SubState.AWAITING_NEXT_MESSAGE,
                persist=True,
            )
        finally:
            self._wf.start_speech(speech)

    async def complete(self, task: HarnessTask, text: str) -> HarnessTask:
        speech = await self._wf.open_speech(task, text)
        try:
            return await self._wf.set_status(task, TaskState.TASK_STATE_COMPLETED, text=text)
        finally:
            self._wf.start_speech(speech)

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
        # A child's signal can run before ``run`` loads the children from the snapshot
        # (a continued run's first activation): it waits here for the load (issue-34).
        self.loaded = False
        self.early_child_done: list[ChildDone] = []
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
        self.intake_message: Message | None = None  # the message the last intake read
        self.noted_media: set[str] = set()  # media the user was told the model cannot take
        self.held_notes: list[str] = []  # status notes waiting for the next turn to start
        self.speak = False  # the message the next reply answers asked for speech (R4.1)
        # The history index of a message whose audio is being transcribed: a cut turn
        # leaves it set, and it is transcribed again before the next run (self-review 2.8).
        self.transcribing: int | None = None
        # Spoken replies being written (design critic 4): a workflow coroutine each, not an
        # update handler, so rollover and completion wait for them explicitly.
        self.speech_jobs: dict[str, SpeechJob] = {}
        self.speech_runs: dict[str, asyncio.Task[None]] = {}
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
        if not self.loaded:
            self.early_child_done.append(done)
            return
        self._apply_child_done(done)

    def _apply_child_done(self, done: ChildDone) -> None:
        terminal = done.state_name in TERMINAL_NAMES
        interrupted = done.state_name in ("INPUT_REQUIRED", "AUTH_REQUIRED")
        remote = False
        task_id = done.task_id
        for i, child in enumerate(self.children):
            # A child is signalled by its workflow: an agent child's stand-in, whose
            # A2A task (the row) has its own id on the agent (issue-34 R7.4).
            if child.workflow_id == done.task_id:
                # A delegated child parking has something to say; a conversation or a
                # participant task parks after every exchange, which is not news.
                remote = child.kind == "remote" or (child.kind == "agent" and child.delegated)
                task_id = child.task_id
                self.children[i] = child.model_copy(
                    update={
                        "done": terminal,
                        "state_name": done.state_name,
                        "sub_state": done.sub_state,
                        "summary": done.summary,
                    }
                )
        if terminal or (remote and interrupted):
            note = f"Sub-task {task_id} is {done.state_name}: {done.summary}"
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
                if self.transcribing is not None:
                    # Before a rollover can drop the mark: the audio the cut turn was
                    # transcribing gets its transcript before the next turn.
                    at, self.transcribing = self.transcribing, None
                    self.state = await self._transcribe(self.state, at=at)
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
            self.speak = out.speak  # the newest message decides whether the reply is spoken
            media = tuple(MediaAttachment(ref=ref) for ref in out.media)
            state = state.append(
                MessageItem(role=MessageRole.USER, text=text, source=out.source, media=media)
            )
            # Committed now, not at the end of the turn: an interrupt that cancels the
            # run restarts from ``self.state`` and must not lose what intake accepted.
            self.state = state
            if out.media and self.intake_message is not None:
                await self._echo(self.intake_message, out)
            if any(ref.kind is MediaKind.AUDIO for ref in out.media):
                self.transcribing = len(state.history) - 1
                state = await self._transcribe(state)
                self.transcribing = None
        return state, accepted

    async def _transcribe(self, state: AgentState, *, at: int = -1) -> AgentState:
        """The audio of the message at ``at``, by default the one just appended (issue-38
        R1.6, R3.4): each attachment the model cannot take natively gets its transcript,
        kept on the attachment in the history and shown as the ``transcript:<mediaId>``
        artifact. Without speech-to-text, or when it fails, the user is told and the turn
        goes on."""
        at = at % len(state.history)
        entry = state.history[at]
        item = entry.item
        if not isinstance(item, MessageItem):
            return state
        media = list(item.media)
        for index, attachment in enumerate(media):
            ref = attachment.ref
            if ref.kind is not MediaKind.AUDIO or attachment.transcript is not None:
                continue
            name = ref.name or ref.id
            try:
                out = await self.call(
                    ActivityName.TRANSCRIBE,
                    TranscribeIn(
                        task_id=self.task.id,
                        correlation_id=self.correlation_id,
                        task=self.task.proto,
                        ref=ref,
                    ),
                    TranscribeOut,
                )
            except ApplicationError:  # retries spent: the turn goes on without it
                out = TranscribeOut(mode="failed")
            if out.mode == "native":
                continue
            if out.mode == "no_stt":
                await self.status_note(
                    f"audio {name} was not given to the model: no speech-to-text is configured"
                )
                continue
            if out.mode == "failed" or out.text is None:
                media[index] = MediaAttachment(ref=ref, transcript=TRANSCRIPTION_FAILED)
                await self.status_note(f"transcription of {name} failed")
                continue
            media[index] = MediaAttachment(ref=ref, transcript=out.text)
            artifact = Artifact(
                artifact_id=f"transcript:{ref.id}", name="transcript", parts=[Part(text=out.text)]
            )
            artifact.metadata.update({"mediaId": ref.id})
            event = TaskArtifactUpdateEvent(
                task_id=self.task.id,
                context_id=self.task.context_id,
                artifact=artifact,
                last_chunk=True,
            )
            await self._deliver(self._emit(event))
        updated = entry.model_copy(update={"item": item.model_copy(update={"media": tuple(media)})})
        history = (*state.history[:at], updated, *state.history[at + 1 :])
        state = state.model_copy(update={"history": history})
        self.state = state
        return state

    async def _echo(self, message: Message, out: IntakeOut) -> None:
        """Log the user's message as stored, its text and its media URLs (issue-38 R6.3),
        so every surface of the task shows the media and any participant can fetch it.
        An artifact update, not a ``Message`` (refused once a task exists) nor a status
        (one in INPUT_REQUIRED would end the sender's stream before the reply)."""
        own = {ref.id for ref in out.media}
        parts: list[Part] = []
        for part in message.parts:
            if part.HasField("text"):
                parts.append(Part(text=part.text))
            elif part.HasField("url") and part.url.rstrip("/").rsplit("/", 1)[-1] in own:
                kept = Part()
                kept.CopyFrom(part)
                parts.append(kept)
        artifact = Artifact(
            artifact_id=f"message:{message.message_id}", name="user message", parts=parts
        )
        artifact.metadata.update(
            {
                "role": "user",
                "participant_id": out.participant_id or "",
                "message_id": message.message_id,
            }
        )
        event = TaskArtifactUpdateEvent(
            task_id=self.task.id,
            context_id=self.task.context_id,
            artifact=artifact,
            last_chunk=True,
        )
        await self._deliver(self._emit(event))

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
        self.intake_message = self.mailbox[0]
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
        try:
            await runner
        except asyncio.CancelledError:
            pass
        except ActivityError as exc:
            # An activity the turn awaited directly (an event's delivery) reports the cut as
            # its own cancellation: that is the cut, not a failure of the task.
            if not isinstance(exc.cause, CancelledError):
                raise
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
            media = tuple(MediaAttachment(ref=ref) for ref in out.media)
            self.state = self.state.append(
                MessageItem(role=MessageRole.USER, text=out.text, media=media)
            )
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
        if state == TaskState.TASK_STATE_CANCELED:
            await self._stop_speech(note=False)  # a cancel stops speech at once
        if state is not None:
            self.task = await self.set_status(self.task, state, text=text)
        await self._drain_speech()  # a last spoken reply plays out, within the drain
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
                        summary=sub_task_result(summary),
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
        self.noted_media = set(start.noted_media)
        self.speak = start.speak
        self.loaded = True
        early, self.early_child_done = self.early_child_done, []
        for done in early:  # a child's change that came before the load (issue-34)
            self._apply_child_done(done)

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
                "noted_media": tuple(sorted(self.noted_media)),
                "speak": self.speak,
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
        await self._drain_speech()  # the snapshot carries no speech job
        await workflow.wait_condition(workflow.all_handlers_finished)
        if self.cancel_reason is not None:
            # The snapshot does not carry a cancel: a run that rolled over now would drop
            # it and wait forever. The caller's next check, or the turn's cut, ends it.
            return
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

    async def status_note(self, text: str) -> None:
        """Tell the task's surfaces ``text`` in a status update that leaves the task as it
        is (issue-38: a media note). The task is not changed, so a turn running beside this
        never sees it. A parked task with a message waiting for its turn holds the note
        until that turn starts: a parked status logged now would end the new message's
        stream before its reply."""
        task = self.task
        waiting = bool(self.mailbox) or self.unanswered or self.completion_by is not None
        if task.state != TaskState.TASK_STATE_WORKING and waiting:
            self.held_notes.append(text)
            return
        status = TaskStatus(state=task.state, timestamp=workflow.now())  # type: ignore[arg-type]
        status.message.CopyFrom(
            text_message(task, text, message_id=f"{task.id}:note:{self.next_seq}")
        )
        event = TaskStatusUpdateEvent(task_id=task.id, context_id=task.context_id, status=status)
        if task.sub_state is not None and STATUS_EXT_KEY in task.proto.metadata.fields:
            event.metadata.fields[STATUS_EXT_KEY].CopyFrom(
                task.proto.metadata.fields[STATUS_EXT_KEY]
            )
        await self._deliver(self._emit(event))

    async def flush_notes(self) -> None:
        notes, self.held_notes = self.held_notes, []
        for note in notes:
            await self.status_note(note)

    async def note_unseen(self, unseen: Sequence[MediaRef]) -> None:
        """R1.7: tell the user, once per image, that the model was not shown it."""
        new = [ref for ref in unseen if ref.id not in self.noted_media]
        if not new:
            return
        self.noted_media.update(ref.id for ref in new)
        names = ", ".join(ref.name or ref.id for ref in new)
        noun = "image" if len(new) == 1 else "images"
        verb = "was" if len(new) == 1 else "were"
        await self.status_note(
            f"{noun} {names} {verb} not given to the model: the model takes no image input"
        )

    # --- spoken replies (issue-38 R4) ---------------------------------------------------

    async def open_speech(self, task: HarnessTask, text: str) -> SpeechJob | None:
        """When the message this reply answers asked for speech and text-to-speech is
        configured: create the speech object and log its ``speech:<id>`` artifact, so the
        URL a surface gets never points at nothing (design critics 1, 2). The flag is
        spent by this reply."""
        speak, self.speak = self.speak, False
        if not speak or not text.strip():
            return None
        media_id = workflow.uuid4().hex
        try:
            out = await workflow.execute_activity(
                ActivityName.OPEN_SPEECH.value,
                OpenSpeechIn(
                    task_id=task.id, correlation_id=self.correlation_id, media_id=media_id
                ),
                result_type=OpenSpeechOut,
                start_to_close_timeout=SHORT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError as exc:
            if isinstance(exc.cause, CancelledError):
                raise asyncio.CancelledError from exc
            workflow.logger.warning("speech not opened: %s", exc.message)
            await self.status_note(SPEECH_UNAVAILABLE)
            return None
        if out.ref is None:
            return None
        part = Part(url=out.url, media_type=out.ref.media_type)
        part.metadata.update({"mediaId": media_id})
        artifact = Artifact(artifact_id=f"speech:{media_id}", name="speech", parts=[part])
        artifact.metadata.update({"mediaId": media_id})
        event = TaskArtifactUpdateEvent(
            task_id=task.id, context_id=task.context_id, artifact=artifact, last_chunk=True
        )
        await self._deliver(self._emit(event))
        return SpeechJob(media_id=media_id, text=text)

    def start_speech(self, job: SpeechJob | None) -> None:
        """Speak the reply as a tracked job beside the loop, so the mailbox keeps
        draining while it plays (the user can speak again at once)."""
        if job is None:
            return
        self.speech_jobs[job.media_id] = job
        self.speech_runs[job.media_id] = asyncio.create_task(self._speak(job))

    async def _speak(self, job: SpeechJob) -> None:
        """The ``speak`` activity, attempt by attempt: each attempt is a new generation of
        the object. A failure once the attempts are spent tells the user (R4.5)."""
        config = self.start.config
        spec = self._policy(ActivityName.SPEAK.value, idempotent=True)
        attempt = 1
        failed = False
        try:
            while True:
                try:
                    await workflow.execute_activity(
                        ActivityName.SPEAK.value,
                        SpeakIn(
                            task_id=self.task.id,
                            correlation_id=self.correlation_id,
                            attempt=attempt,
                            media_id=job.media_id,
                            text=job.text,
                            voice=job.voice,
                            max_attempts=spec.maximum_attempts,
                        ),
                        start_to_close_timeout=config.tool_timeout,
                        heartbeat_timeout=config.heartbeat_timeout,
                        retry_policy=ONE_ATTEMPT,
                        # A cancel waits for the activity to close its object failed.
                        cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                    )
                    break
                except ActivityError as exc:
                    if isinstance(exc.cause, CancelledError):
                        raise asyncio.CancelledError from exc
                    info = _error_info(exc)
                    if is_non_retryable(info, spec) or attempt >= spec.maximum_attempts:
                        workflow.logger.warning("speech failed: %s", info.message)
                        failed = True
                        break
                    await workflow.sleep(backoff(spec, attempt))
                    attempt += 1
        finally:
            self.speech_jobs.pop(job.media_id, None)
            self.speech_runs.pop(job.media_id, None)
        if failed:
            await self.status_note(SPEECH_UNAVAILABLE)

    async def _drain_speech(self) -> None:
        """Wait, at most ``speech_drain``, for the spoken replies to finish; stop any still
        running then, with the note (design critic 4). A cancel ends the wait."""
        if not self.speech_jobs:
            return
        with contextlib.suppress(TimeoutError):
            await workflow.wait_condition(
                lambda: not self.speech_jobs or self.cancel_reason is not None,
                timeout=self.start.config.speech_drain,
            )
        await self._stop_speech(note=True)

    async def _stop_speech(self, *, note: bool) -> None:
        """Cancel every running speech job and wait for each activity to close its object
        failed; with ``note``, tell the user speech is unavailable."""
        runs = list(self.speech_runs.values())
        if not runs:
            return
        for run in runs:
            run.cancel()
        for run in runs:
            with contextlib.suppress(asyncio.CancelledError, ActivityError):
                await run
        self.speech_jobs.clear()
        self.speech_runs.clear()
        if note:
            await self.status_note(SPEECH_UNAVAILABLE)

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

    async def show_media(self, task: HarnessTask, result: ToolResult, urls: dict[str, str]) -> None:
        """Each media part of a tool result (``generate_image``, issue-38 R2.2) as the
        ``image:<mediaId>`` artifact: one url file part, named by the alt text."""
        for content in result.content:
            ref = content.media
            if content.kind != "media" or ref is None or ref.id not in urls:
                continue
            part = Part(url=urls[ref.id], media_type=ref.media_type, filename=ref.name)
            part.metadata.update({"mediaId": ref.id})
            artifact = Artifact(
                artifact_id=f"{ref.kind.value}:{ref.id}",
                name=content.text or ref.name,
                parts=[part],
            )
            artifact.metadata.update({"mediaId": ref.id})
            event = TaskArtifactUpdateEvent(
                task_id=task.id, context_id=task.context_id, artifact=artifact, last_chunk=True
            )
            await self._deliver(self._emit(event))

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
        description = str(payload.get("description") or "")
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
            # A task on this harness for its assignee (issue-34 R7.2): the brief alone,
            # which this harness creates in participant mode, waiting for the assignee.
            brief = brief_message(
                child_id,
                task.context_id,
                sender=self.start.config.agent,
                text="",
                envelope=ext.model_dump(
                    mode="json",
                    include={"name", "goal", "acceptance_criteria", "participants", "parent_tasks"},
                    exclude_none=True,
                ),
            )
            return await self._start_agent_child(
                HarnessTask.new(child_id, task.context_id, ext),
                agent=SELF_AGENT_ID,
                brief=brief,
                step=step,
                delegated=False,
            )
        # Every agent child, this harness's own included, is an A2A task on its agent
        # (issue-34 R7.2): ``agent`` null is ``self``.
        target = str(agent) if agent else SELF_AGENT_ID
        mine = target == SELF_AGENT_ID
        ext = child_extension(
            task,
            name=name,
            goal=goal,
            criteria=criteria,
            participants=task.ext.participants,
            lifecycle="delegated",
            inherit=mine,  # another agent runs on its own model
            description=description,
        )
        # This harness trusts itself to brief a child fully (issue-34 R7): it finishes by
        # itself on the parent's settings. Another agent gets the open fields, which any
        # creator may set; a peer that ignores the lifecycle is still read as done when it
        # parks awaiting its next message.
        fields = {"name", "goal", "description", "acceptance_criteria"}
        if mine:
            fields |= {"lifecycle", "model", "reasoning_effort", "parent_tasks"}
        brief = brief_message(
            child_id,
            task.context_id,
            sender=self.start.config.agent,
            text=sub_task_brief(goal, description, [c.text for c in criteria]),
            envelope=ext.model_dump(mode="json", include=fields, exclude_none=True),
        )
        return await self._start_agent_child(
            HarnessTask.new(child_id, task.context_id, ext),
            agent=target,
            brief=brief,
            step=step,
            delegated=True,
        )

    async def _start_agent_child(
        self,
        record: HarnessTask,
        *,
        agent: str,
        brief: Message,
        step: str | None,
        delegated: bool,
    ) -> TaskRef:
        """Create a child task on ``agent`` with its brief, then follow it with a stand-in
        (issue-34 R7.2). The row names the child's own A2A task on the agent (R7.4). A
        child that could not be created, or ended in its first answer, is resolved here
        and its parent is told as of any child's end."""
        config = self.start.config
        # The row says where the task lives: a child on ``self`` is on this harness, which
        # ``TaskRef`` writes as no agent, so every surface opens it as its own (R7.4).
        agent_ref = None if agent == SELF_AGENT_ID else EntityRef(kind=EntityKind.AGENT, id=agent)
        stand_in = record.id
        try:
            out = await workflow.execute_activity(
                ActivityName.START_AGENT_TASK.value,
                StartAgentTaskIn(
                    task_id=stand_in,
                    correlation_id=self.correlation_id,
                    agent=agent,
                    message=brief,
                    delegated=delegated,
                ),
                result_type=RemoteTurnOut,
                start_to_close_timeout=config.tool_timeout,
                heartbeat_timeout=config.heartbeat_timeout,
                retry_policy=ONE_ATTEMPT,  # a create is not idempotent
            )
        except ActivityError as exc:
            reason = _error_info(exc).message
            out = RemoteTurnOut(remote_task_id="", state_name="FAILED", text=reason, final=True)
        task_id = out.remote_task_id or stand_in
        child = ChildRef(
            task_id=task_id,
            workflow_id=stand_in,
            kind="agent",
            step=step,
            delegated=delegated,
            state_name=out.state_name,
            sub_state=out.sub_state,
        )
        if out.final or not out.remote_task_id:
            summary = sub_task_result(out.text)
            self.children.append(child.model_copy(update={"done": True, "summary": summary}))
            self.notes.append(f"Sub-task {task_id} is {out.state_name}: {summary}".strip())
            return TaskRef(
                task_id=task_id, agent=agent_ref, state=out.state_name, sub_state=out.sub_state
            )
        await workflow.start_child_workflow(
            "RemoteTaskWorkflow",
            RemoteStart(
                task=record.proto,
                agent=agent,
                goal=sub_task_brief(record.ext.goal, record.ext.description, []),
                parent_workflow_id=workflow.info().workflow_id,
                correlation_id=self.correlation_id,
                config=config,
                delegated=delegated,
                resume=RemoteResume(remote_task_id=out.remote_task_id, watch=None, last=out),
            ),
            id=stand_in,
            parent_close_policy=workflow.ParentClosePolicy.ABANDON,
        )
        self.children.append(child)
        return TaskRef(task_id=task_id, agent=agent_ref)

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
        # A conversation on this harness, created through its own A2A interface with the
        # brief alone, so it waits for its reporter's first message (issue-34 R7.2).
        brief = brief_message(
            child_id,
            task.context_id,
            sender=self.start.config.agent,
            text="",
            envelope=ext.model_dump(
                mode="json",
                include={
                    "name",
                    "goal",
                    "participants",
                    "lifecycle",
                    "model",
                    "reasoning_effort",
                    "parent_tasks",
                },
                exclude_none=True,
            ),
        )
        ref = await self._start_agent_child(
            HarnessTask.new(child_id, task.context_id, ext),
            agent=SELF_AGENT_ID,
            brief=brief,
            step=None,
            delegated=False,
        )
        self.task = link_subtask(task, ref, None)
        return ref

    # --- the activity wrapper (R19.3-R19.6) -----------------------------------------

    def _policy(self, name: str, *, idempotent: bool) -> RetryPolicySpec:
        spec = self.start.config.retries.for_activity(name)
        if not idempotent:
            spec = spec.model_copy(update={"maximum_attempts": 1})
        return spec

    def _timeouts(self, name: ActivityName) -> tuple[timedelta, timedelta | None]:
        """LLM, tool and compaction activities heartbeat; the rest are short (R19.6)."""
        config = self.start.config
        if name in (ActivityName.INVOKE_LLM, ActivityName.COMPACT, ActivityName.TRANSCRIBE):
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
            self.cancel_reason = self.cancel_reason or resumed.cancel_reason
            self.claimed, self.recheck = resumed.claimed, resumed.recheck
            # A continued run reconciles across the gap; a new stand-in (no watch yet,
            # issue-34 R7.2) registers its watch, which fetches once, when it parks.
            self.push_pending = resumed.watch is not None and resumed.watch.mode == "push"
            self.task = self.task.with_state(
                TaskState.Value(f"TASK_STATE_{resumed.last.state_name}")
            )
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
                        delegated=start.delegated,
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
                # A push during the turn still fetches once (R2.8), but its claim described
                # the stream the turn already read: it must not start rechecks.
                self.recheck, self.claimed = None, ""
            resumed = None
            parked = await self._park()
            if parked == "roll":  # a pending recheck goes with it (R2.9)
                workflow.continue_as_new(self._resume())
            self.recheck, self.claimed = None, ""  # a recheck belongs to one park only
            if parked == "ended":
                return await self._end()
            if self.cancel_reason is not None:
                await self._cancel_remote()
                self.task = self.task.with_state(TaskState.TASK_STATE_CANCELED)
                await self._tell_parent(
                    RemoteTurnOut(remote_task_id=self.remote_task_id or "", state_name="CANCELED")
                )
                return await self._end()
            reply = self.mailbox.pop(0)
            outbound = Message()
            outbound.CopyFrom(reply)
            outbound.task_id = self.remote_task_id or ""
            # The remote task knows this harness, not whoever replied here (R1.6).
            outbound.metadata.update({"participant_id": start.config.agent})

    def _resume(self) -> RemoteStart:
        """The next run's input: the same stand-in, still parked (history bound, R19.8)."""
        assert self.start is not None and self.watch is not None
        return self.start.model_copy(
            update={
                "task": self.task.proto,
                "mailbox": tuple(self.mailbox),
                "resume": RemoteResume(
                    remote_task_id=self.remote_task_id or "",
                    watch=self.watch,
                    last=self.last,
                    cancel_reason=self.cancel_reason,
                    claimed=self.claimed,
                    recheck=self.recheck,
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
            delegated=self.start.delegated,
            known_text=self.last.text,
        )

    async def _cancel_remote(self) -> None:
        """The parent was cancelled: cancel the child on its agent, best effort; the
        stand-in ends cancelled whatever the agent answers (issue-34 R7.6)."""
        if not self.remote_task_id:
            return
        try:
            await workflow.execute_activity(
                ActivityName.CANCEL_REMOTE_TASK.value,
                self._remote_in(),
                start_to_close_timeout=SHORT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except ActivityError as exc:
            workflow.logger.warning("cancelling the child on its agent failed: %s", exc.message)

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
            if self._interrupted():
                return "interrupted"  # before a rollover, so a cancel is never carried over
            if self._history_full():
                return "roll"
            follow: workflow.ActivityHandle[FollowOut] | None = None
            # ``off`` watches no parked task, but a child still working must be followed
            # until it parks or ends: a new stand-in has read no turn's stream (R7.2).
            working = self.last.state_name in ("SUBMITTED", "WORKING")
            if watch.mode == "follow" or (watch.mode == "off" and working):
                follow = workflow.start_activity(
                    ActivityName.FOLLOW_REMOTE_TASK.value,
                    FollowIn(**self._remote_in().model_dump(), known_state=self.last.state_name),
                    result_type=FollowOut,
                    start_to_close_timeout=FOLLOW_WINDOW + timedelta(minutes=1),
                    heartbeat_timeout=self.start.config.heartbeat_timeout,
                    retry_policy=ONE_ATTEMPT,
                )
            try:
                await workflow.wait_condition(self._woken(follow), timeout=self._recheck_delay())
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
                    # Keep the last state (fail closed); a recheck still due tries again, and
                    # the next push does after the last one.
                    active = self.last.state_name in ("SUBMITTED", "WORKING")
                    if self.recheck is None and active:
                        # A new stand-in's child may already have parked, and no push will
                        # tell of it again: retry the fetch on the bounded rechecks
                        # (issue-34 R7.2).
                        self.recheck = 0
                    elif self._recheck_delay() is None:
                        self.recheck, self.claimed = None, ""
                    continue
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

    def _recheck_delay(self) -> timedelta | None:
        if self.recheck is None or self.recheck >= len(PUSH_RECHECKS):
            return None
        return PUSH_RECHECKS[self.recheck]

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
        changed = (out.state_name, out.sub_state, out.text) != (
            self.last.state_name,
            self.last.sub_state,
            self.last.text,
        )
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
                ChildDone(
                    task_id=self.task.id,
                    state_name=out.state_name,
                    sub_state=out.sub_state,
                    summary=sub_task_result(out.text),
                ),
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
