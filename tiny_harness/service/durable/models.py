"""Workflow and activity payloads (R19.10): typed models carried by the Pydantic data
converter. A2A protos travel as ProtoJSON fields; nothing here holds a secret.

``TaskStart`` is the complete workflow state, so ``continue_as_new`` carries it whole
(R19.8). Every activity input extends ``ActivityIn`` so the attempt number is in the
recorded payload (R19.4).
"""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Literal

from a2a.types import Message, Task, TaskArtifactUpdateEvent, TaskStatusUpdateEvent
from google.protobuf import json_format
from pydantic import BaseModel, ConfigDict, Field

from tiny_harness.config import RetryPolicies, RetryPolicySpec
from tiny_harness.harness.channels import ChannelMessage
from tiny_harness.harness.core import (
    AgentState,
    CompactionRecord,
    ContextWindow,
    TaskRef,
    proto_json,
)
from tiny_harness.harness.hooks import HookContext
from tiny_harness.harness.models import LLMRequest, LLMResponse
from tiny_harness.harness.tools import ToolCall, ToolResult, WorkflowCommand
from tiny_harness.interaction.a2ui import SurfaceRegistry
from tiny_harness.jsontypes import JsonObject

type TaskProto = Annotated[Task, *proto_json(Task)]
type MessageProto = Annotated[Message, *proto_json(Message)]
type A2AEventProto = Message | Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent
type EventKind = Literal["task", "message", "status_update", "artifact_update"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActivityName(StrEnum):
    """Every activity the worker registers; the workflow calls them by name (R19.1)."""

    INTAKE = "intake"
    ASSEMBLE_CONTEXT = "assemble_context"
    COMPACTION_TRIGGER = "compaction_trigger"
    COMPACT = "compact"
    INVOKE_LLM = "invoke_llm"
    INVOKE_TOOL = "invoke_tool"
    DECIDE_COMPLETION = "decide_completion"
    PERSIST = "persist"
    SEND_CHANNEL_MESSAGE = "send_channel_message"
    EMIT_EVENT = "emit_event"
    DISPATCH_HOOKS = "dispatch_hooks"
    RUN_REMOTE_AGENT_TURN = "run_remote_agent_turn"
    POLL_CHANNELS = "poll_channels"
    MONITOR_SNAPSHOT = "monitor_snapshot"
    RETENTION_SWEEP = "retention_sweep"


# --- the durable event log ------------------------------------------------------------


class EventEntry(_Frozen):
    """One A2A event in the task's durable log, as ProtoJSON, with a monotonic sequence."""

    seq: int
    kind: EventKind
    payload: JsonObject


def event_entry(seq: int, event: A2AEventProto) -> EventEntry:
    kind: EventKind
    if isinstance(event, Task):
        kind = "task"
    elif isinstance(event, Message):
        kind = "message"
    elif isinstance(event, TaskStatusUpdateEvent):
        kind = "status_update"
    else:
        kind = "artifact_update"
    payload = json_format.MessageToDict(event, preserving_proto_field_name=False)
    return EventEntry(seq=seq, kind=kind, payload=payload)


def entry_event(entry: EventEntry) -> A2AEventProto:
    if entry.kind == "task":
        return json_format.ParseDict(entry.payload, Task())
    if entry.kind == "message":
        return json_format.ParseDict(entry.payload, Message())
    if entry.kind == "status_update":
        return json_format.ParseDict(entry.payload, TaskStatusUpdateEvent())
    return json_format.ParseDict(entry.payload, TaskArtifactUpdateEvent())


class EventPage(_Frozen):
    """What ``events_since`` returns: the entries from the cursor and the next cursor."""

    events: tuple[EventEntry, ...]
    next_seq: int
    closed: bool


# --- workflow state -------------------------------------------------------------------


class HelpRequest(_Frozen):
    """The open ``ask_participant``: who was asked what, and the message that carried it."""

    participant_id: str
    question: str
    options: tuple[str, ...] = ()
    message_id: str
    call_id: str


class ChildRef(_Frozen):
    """A child task workflow this task waits on (local, participant or remote)."""

    task_id: str
    workflow_id: str
    kind: Literal["local", "participant", "remote"]
    step: str | None = None
    done: bool = False
    state_name: str = "SUBMITTED"
    summary: str = ""


class ChildDone(_Frozen):
    """The signal a child sends its parent when it reaches a terminal state."""

    task_id: str
    state_name: str
    summary: str = ""


class WorkflowConfig(_Frozen):
    """Deterministic configuration the workflow carries (R19.3, R19.8)."""

    agent: str = "tiny-harness"
    retries: RetryPolicies = RetryPolicies()
    history_event_bound: int = 10_000
    max_turns: int = 50
    search_attributes: bool = True
    heartbeat_timeout: timedelta = timedelta(seconds=30)
    llm_timeout: timedelta = timedelta(seconds=120)
    tool_timeout: timedelta = timedelta(seconds=300)


class TaskStart(_Frozen):
    """The complete workflow state; the first run starts from an empty state (R19.8)."""

    task: TaskProto
    state: AgentState
    mode: Literal["agent", "participant"] = "agent"
    config: WorkflowConfig = WorkflowConfig()
    correlation_id: str = ""
    mailbox: tuple[MessageProto, ...] = ()
    seen_message_ids: tuple[str, ...] = ()
    events: tuple[EventEntry, ...] = ()
    next_event_seq: int = 0
    pending_help: HelpRequest | None = None
    children: tuple[ChildRef, ...] = ()
    notes: tuple[str, ...] = ()
    attempt_counters: dict[str, int] = Field(default_factory=dict)
    parent_workflow_id: str | None = None
    surfaces: SurfaceRegistry = SurfaceRegistry()


class InboxReceipt(_Frozen):
    """What the ``inbox`` update returns: the message is in history before this exists."""

    message_id: str
    accepted: bool
    duplicate: bool = False
    state_name: str
    cursor: int


# --- activity payloads ----------------------------------------------------------------


class ActivityIn(_Frozen):
    task_id: str
    correlation_id: str
    attempt: int = 1


class IntakeIn(ActivityIn):
    task: TaskProto
    message: MessageProto
    surfaces: SurfaceRegistry = SurfaceRegistry()


class IntakeOut(_Frozen):
    accepted: bool
    text: str = ""
    participant_id: str | None = None
    source: str | None = None  # "agent" when the sender is an agent: framed as untrusted
    reason: str = ""
    interrupt: bool = False
    task: TaskProto | None = None
    ui_action: JsonObject | None = None


class AssembleIn(ActivityIn):
    task: TaskProto
    state: AgentState


class TriggerIn(ActivityIn):
    task: TaskProto
    window: ContextWindow


class TriggerOut(_Frozen):
    compact: bool


class CompactIn(ActivityIn):
    task: TaskProto
    state: AgentState
    window: ContextWindow


class CompactOut(_Frozen):
    state: AgentState
    record: CompactionRecord


class LLMIn(ActivityIn):
    task: TaskProto
    request: LLMRequest


class LLMTurn(_Frozen):
    """The recorded result: the response and the calls the ``tool_calls.extracted`` chain
    let through, so the workflow extracts from history, never from a model."""

    response: LLMResponse
    calls: tuple[ToolCall, ...]


class ToolIn(ActivityIn):
    task: TaskProto
    actor: str | None
    call: ToolCall


class ToolOut(_Frozen):
    result: ToolResult | WorkflowCommand


class CompletionIn(ActivityIn):
    task: TaskProto
    unresolved: tuple[TaskRef, ...]


class CompletionOut(_Frozen):
    result: Literal["wait", "complete", "fail"]
    reason: str = ""


class PersistIn(ActivityIn):
    task: TaskProto
    state: AgentState
    compaction: CompactionRecord | None = None
    events: tuple[EventEntry, ...] = ()
    final: bool = False


class ChannelSendIn(ActivityIn):
    task: TaskProto
    message: ChannelMessage


class EmitIn(ActivityIn):
    context_id: str
    entry: EventEntry


# --- remote agents (R7.3) ----------------------------------------------------------------


class RemoteStart(_Frozen):
    """A delegated sub-task: the local task record, the agent it runs on, the parent."""

    task: TaskProto
    agent: str
    goal: str
    parent_workflow_id: str
    correlation_id: str = ""
    config: WorkflowConfig = WorkflowConfig()
    mailbox: tuple[MessageProto, ...] = ()


class RemoteTurnIn(ActivityIn):
    agent: str
    message: MessageProto
    remote_task_id: str | None = None


class RemoteTurnOut(_Frozen):
    remote_task_id: str
    state_name: str
    text: str = ""
    final: bool = False


# --- heartbeat (R16) -------------------------------------------------------------------


class HeartbeatTick(_Frozen):
    """One schedule tick's input; the schedule starts a ``HeartbeatWorkflow`` with it."""

    task_queue: str = "tiny-harness"


class TaskMonitor(_Frozen):
    """What ``monitor`` returns per task: the inner layer's view (R16.3)."""

    task_id: str
    context_id: str
    state_name: str
    mailbox: int = 0
    pending_help: bool = False
    children: int = 0
    turn: int = 0


class MonitorSnapshot(_Frozen):
    at: str
    tasks: tuple[TaskMonitor, ...] = ()
    pending_help: int = 0
    queued_messages: int = 0


class HeartbeatTickPre(HookContext):
    snapshot: MonitorSnapshot


class PollIn(ActivityIn):
    pass


class PollOut(_Frozen):
    forwarded: int
    channels: int


class MonitorIn(ActivityIn):
    pass


class SweepIn(ActivityIn):
    pass


class SweepOut(_Frozen):
    deleted: dict[str, int]


class HeartbeatResult(_Frozen):
    forwarded: int
    tasks: int
    deleted: dict[str, int]


class ErrorInfo(_Frozen):
    type: str
    message: str
    non_retryable: bool = False


class ActivityFailedPre(HookContext):
    activity: str
    error: ErrorInfo
    policy: RetryPolicySpec


class ActivityRetriedPre(HookContext):
    activity: str
    policy: RetryPolicySpec
    next_delay: timedelta


class RetryIn(ActivityIn):
    activity: str
    error: ErrorInfo
    policy: RetryPolicySpec
    next_delay: timedelta


class RetryOut(_Frozen):
    policy: RetryPolicySpec
    next_delay: timedelta
    abort: str | None = None


__all__ = [
    "A2AEventProto",
    "ActivityFailedPre",
    "ActivityIn",
    "ActivityName",
    "ActivityRetriedPre",
    "AssembleIn",
    "ChannelSendIn",
    "ChildDone",
    "ChildRef",
    "CompactIn",
    "CompactOut",
    "CompletionIn",
    "CompletionOut",
    "EmitIn",
    "ErrorInfo",
    "EventEntry",
    "EventKind",
    "EventPage",
    "HeartbeatResult",
    "HeartbeatTick",
    "HeartbeatTickPre",
    "HelpRequest",
    "InboxReceipt",
    "IntakeIn",
    "IntakeOut",
    "LLMIn",
    "LLMTurn",
    "MessageProto",
    "MonitorIn",
    "MonitorSnapshot",
    "PersistIn",
    "PollIn",
    "PollOut",
    "RemoteStart",
    "RemoteTurnIn",
    "RemoteTurnOut",
    "RetryIn",
    "RetryOut",
    "SweepIn",
    "SweepOut",
    "TaskMonitor",
    "TaskProto",
    "TaskStart",
    "ToolIn",
    "ToolOut",
    "TriggerIn",
    "TriggerOut",
    "WorkflowConfig",
    "entry_event",
    "event_entry",
]
