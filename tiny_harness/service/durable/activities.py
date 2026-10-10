"""The activities (R19.1): each is a hook-wrapped body over the in-process host, so the
same code the Layer 4 tests exercise runs on the worker. LLM and tool activities
heartbeat every 10 s so a dead worker is detected within ``heartbeat_timeout`` (R19.6).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from a2a.types import Message, Part, Task, TaskState, TaskStatusUpdateEvent
from a2a.types import Role as A2ARole
from google.protobuf import json_format, struct_pb2
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowUpdateFailedError
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError

from tiny_harness.errors import HookAbort, ProviderError, TinyHarnessError, ToolNotFoundError
from tiny_harness.harness.agents import SUPPORTED_EXTENSIONS, Agent
from tiny_harness.harness.channels import (
    CHANNEL_EXT_MEDIA_TYPE,
    Channel,
    ChannelMessage,
    ChannelMessageData,
)
from tiny_harness.harness.core import (
    AgentState,
    CompletionDecision,
    HarnessTask,
    TaskCompleteIn,
    participant_of,
)
from tiny_harness.harness.core.context import ContextWindow
from tiny_harness.harness.core.inprocess import InProcessOperations
from tiny_harness.harness.core.loop import RequestReceivedPost, RequestReceivedPre
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.hooks import HookPoint, Operation, Phase
from tiny_harness.harness.persistence import (
    ChannelMessageRecord,
    CompactionStoreRecord,
    InboxAuditRecord,
    PlanRecord,
    RecordKind,
    StateRecord,
    TaskRecord,
)
from tiny_harness.interaction.a2ui import (
    A2UI_MEDIA_TYPE,
    A2UIValidationError,
    Action,
    parse_client_message,
)
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.durable.models import (
    ActivityFailedPre,
    ActivityName,
    ActivityRetriedPre,
    AssembleIn,
    ChannelSendIn,
    CompactIn,
    CompactOut,
    CompletionIn,
    CompletionOut,
    EmitIn,
    EventEntry,
    HeartbeatTickPre,
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
    RemoteTurnIn,
    RemoteTurnOut,
    RetryIn,
    RetryOut,
    SweepIn,
    SweepOut,
    TaskMonitor,
    ToolIn,
    ToolOut,
    TriggerIn,
    TriggerOut,
)

HEARTBEAT_EVERY = 10.0
TERMINAL = frozenset(
    {
        TaskState.TASK_STATE_COMPLETED,
        TaskState.TASK_STATE_FAILED,
        TaskState.TASK_STATE_CANCELED,
        TaskState.TASK_STATE_REJECTED,
    }
)
NON_RETRYABLE_CODES = frozenset({ProviderError.code, HookAbort.code, ToolNotFoundError.code})


class EventSink(Protocol):
    """Where ``emit_event`` delivers: push notification configs, in the server process."""

    async def deliver(self, task_id: str, context_id: str, entry: EventEntry) -> None: ...


async def _heartbeating[T](coro: Awaitable[T], *, every: float = HEARTBEAT_EVERY) -> T:
    task = asyncio.ensure_future(coro)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=every)
            if done:
                return task.result()
            activity.heartbeat()
    finally:
        if not task.done():
            task.cancel()


def _translate(exc: TinyHarnessError) -> ApplicationError:
    return ApplicationError(
        exc.message,
        exc.to_record(),
        type=exc.code,
        non_retryable=exc.code in NON_RETRYABLE_CODES,
    )


class Activities:
    """The worker's activity set, bound to one in-process host (registry, hooks, LLM, store)."""

    def __init__(
        self,
        engine: InProcessOperations,
        *,
        sink: EventSink | None = None,
        client: Client | None = None,
        retention: Mapping[RecordKind, timedelta] | None = None,
    ) -> None:
        self.engine = engine
        self.sink = sink
        self.client = client
        self.retention: dict[RecordKind, timedelta] = dict(retention or {})
        self.last_snapshot: MonitorSnapshot | None = None
        self.heartbeat_every = HEARTBEAT_EVERY

    def all(self) -> Sequence[Callable[..., Awaitable[object]]]:
        return (
            self.intake,
            self.assemble_context,
            self.compaction_trigger,
            self.compact,
            self.invoke_llm,
            self.invoke_tool,
            self.decide_completion,
            self.persist,
            self.send_channel_message,
            self.emit_event,
            self.dispatch_hooks,
            self.run_remote_agent_turn,
            self.poll_channels,
            self.monitor_snapshot,
            self.retention_sweep,
        )

    # --- intake (R15, abuse cases 4 and 6) ------------------------------------------

    @activity.defn(name=ActivityName.INTAKE.value)
    async def intake(self, arg: IntakeIn) -> IntakeOut:
        task = HarnessTask(arg.task)
        participant = participant_of(arg.message)
        text = "\n".join(p.text for p in arg.message.parts if p.HasField("text"))
        now = datetime.now(UTC)
        # Fail closed (abuse case 4): a message must assert a participant who is on the
        # task; the executor fills the assertion from the perimeter's header when the
        # message carries none, so a message with neither is refused here.
        accepted = participant is not None and task.ext.is_participant(participant)
        reason = (
            ""
            if accepted
            else ("no participant asserted" if participant is None else "not a participant")
        )
        ui_action: JsonObject | None = None
        if accepted:
            try:
                action = ui_action_of(arg.message)
            except A2UIValidationError as exc:
                accepted, reason = False, f"{exc.code}: {exc.message}"
            else:
                if action is not None:
                    if arg.surfaces.accepts(action):
                        ui_action = action.payload()
                        text = (text + "\n" if text else "") + describe_action(action)
                    else:  # abuse case 9: a surface or component the task did not create
                        accepted, reason = False, "a2ui.unknown_surface_or_component"
        try:
            if accepted:
                pre = RequestReceivedPre(
                    task_id=task.id,
                    correlation_id=arg.correlation_id,
                    attempt=arg.attempt,
                    text=text,
                )

                async def body(ctx: RequestReceivedPre) -> str:
                    return ctx.text

                text = await self.engine.runner.run(
                    Operation.REQUEST_RECEIVED,
                    pre,
                    body,
                    make_post=lambda p, out: RequestReceivedPost(
                        task_id=p.task_id,
                        correlation_id=p.correlation_id,
                        attempt=p.attempt,
                        text=out,
                        state=AgentState(task_id=task.id),
                    ),
                    extract=lambda post: post.text,
                )
        except HookAbort as exc:
            accepted, reason = False, f"{exc.code}: {exc.message}"
        await self.engine.store.put(
            InboxAuditRecord(
                id=arg.message.message_id or f"{task.id}:{now.isoformat()}",
                context_id=task.context_id,
                task_id=task.id,
                created_at=now,
                message_id=arg.message.message_id,
                participant_id=participant,
                accepted=accepted,
                reason=reason,
            )
        )
        interrupt = False
        if arg.message.HasField("metadata") and "interrupt" in arg.message.metadata.fields:
            interrupt = bool(arg.message.metadata.fields["interrupt"].bool_value)
        return IntakeOut(
            accepted=accepted,
            text=text if accepted else "",
            participant_id=participant,
            reason=reason,
            interrupt=interrupt,
            ui_action=ui_action if accepted else None,
        )

    # --- the loop's operations ------------------------------------------------------

    @activity.defn(name=ActivityName.ASSEMBLE_CONTEXT.value)
    async def assemble_context(self, arg: AssembleIn) -> ContextWindow:
        try:
            return await self.engine.assemble(HarnessTask(arg.task), arg.state)
        except TinyHarnessError as exc:
            raise _translate(exc) from exc

    @activity.defn(name=ActivityName.COMPACTION_TRIGGER.value)
    async def compaction_trigger(self, arg: TriggerIn) -> TriggerOut:
        self.engine.correlation_id = arg.correlation_id
        return TriggerOut(
            compact=await self.engine.should_compact(HarnessTask(arg.task), arg.window)
        )

    @activity.defn(name=ActivityName.COMPACT.value)
    async def compact(self, arg: CompactIn) -> CompactOut:
        self.engine.correlation_id = arg.correlation_id
        state, record = await _heartbeating(
            self.engine.compact(HarnessTask(arg.task), arg.state, arg.window),
            every=self.heartbeat_every,
        )
        return CompactOut(state=state, record=record)

    @activity.defn(name=ActivityName.INVOKE_LLM.value)
    async def invoke_llm(self, arg: LLMIn) -> LLMTurn:
        self.engine.correlation_id = arg.correlation_id
        task = HarnessTask(arg.task)
        self.engine.context.task = task
        try:
            response = await _heartbeating(
                self.engine.invoke_llm(task, arg.request), every=self.heartbeat_every
            )
            calls = await self.engine.extract(task, response)
        except TinyHarnessError as exc:
            raise _translate(exc) from exc
        return LLMTurn(response=response, calls=calls)

    @activity.defn(name=ActivityName.INVOKE_TOOL.value)
    async def invoke_tool(self, arg: ToolIn) -> ToolOut:
        self.engine.correlation_id = arg.correlation_id
        self.engine.context.actor = arg.actor
        try:
            result = await _heartbeating(
                self.engine.invoke_tool(HarnessTask(arg.task), arg.call), every=self.heartbeat_every
            )
        except TinyHarnessError as exc:
            raise _translate(exc) from exc
        return ToolOut(result=result)

    @activity.defn(name=ActivityName.DECIDE_COMPLETION.value)
    async def decide_completion(self, arg: CompletionIn) -> CompletionOut:
        ctx = TaskCompleteIn(
            task_id=arg.task_id, correlation_id=arg.correlation_id, unresolved=arg.unresolved
        )
        try:
            out = await self.engine.runner.run_in(Operation.TASK_COMPLETE, ctx)
        except HookAbort as exc:
            return CompletionOut(result="fail", reason=exc.message)
        decision = out.result or CompletionDecision.COMPLETE
        return CompletionOut(result=decision.value, reason=out.reason)

    @activity.defn(name=ActivityName.PERSIST.value)
    async def persist(self, arg: PersistIn) -> None:
        task = HarnessTask(arg.task)
        now = datetime.now(UTC)
        redactor = self.engine.runner.redactor
        await self.engine.store.put(
            redactor.scrub(
                TaskRecord(
                    id=task.id,
                    context_id=task.context_id,
                    task_id=task.id,
                    created_at=now,
                    task=task.proto,
                    state_name=task.state_name,
                    events=tuple(e.payload for e in arg.events),
                )
            )
        )
        if task.ext.plan is not None:
            await self.engine.store.put(
                PlanRecord(
                    id=f"{task.id}:{arg.state.turn}",
                    context_id=task.context_id,
                    task_id=task.id,
                    created_at=now,
                    plan=task.ext.plan,
                    turn=arg.state.turn,
                )
            )
        await self.engine.store.put(
            redactor.scrub(StateRecord.from_state(arg.state, context_id=task.context_id, at=now))
        )
        if arg.compaction is not None:
            await self.engine.store.put(
                CompactionStoreRecord(
                    id=f"{task.id}:{arg.compaction.turn}",
                    context_id=task.context_id,
                    task_id=task.id,
                    created_at=now,
                    record=arg.compaction,
                )
            )

    @activity.defn(name=ActivityName.SEND_CHANNEL_MESSAGE.value)
    async def send_channel_message(self, arg: ChannelSendIn) -> None:
        task = HarnessTask(arg.task)
        message = self.engine.runner.redactor.scrub(arg.message)
        await self.engine.store.put(
            ChannelMessageRecord(
                id=message.id,
                context_id=task.context_id,
                task_id=task.id,
                created_at=message.at,
                channel_id=message.channel_id,
                sender=message.sender,
                message_kind=message.kind,
                parts=message.parts,
            )
        )

    @activity.defn(name=ActivityName.EMIT_EVENT.value)
    async def emit_event(self, arg: EmitIn) -> None:
        if self.sink is not None:
            await self.sink.deliver(arg.task_id, arg.context_id, arg.entry)

    # --- workflow-managed retries (R19.3, R19.4) -----------------------------------

    @activity.defn(name=ActivityName.DISPATCH_HOOKS.value)
    async def dispatch_hooks(self, arg: RetryIn) -> RetryOut:
        hooks = self.engine.hooks
        try:
            failed = await hooks.run(
                HookPoint(operation=Operation.ACTIVITY_FAILED, phase=Phase.PRE),
                ActivityFailedPre(
                    task_id=arg.task_id,
                    correlation_id=arg.correlation_id,
                    attempt=arg.attempt,
                    activity=arg.activity,
                    error=arg.error,
                    policy=arg.policy,
                ),
            )
            retried = await hooks.run(
                HookPoint(operation=Operation.ACTIVITY_RETRIED, phase=Phase.PRE),
                ActivityRetriedPre(
                    task_id=arg.task_id,
                    correlation_id=arg.correlation_id,
                    attempt=arg.attempt,
                    activity=arg.activity,
                    policy=failed.policy,
                    next_delay=arg.next_delay,
                ),
            )
        except HookAbort as exc:
            return RetryOut(policy=arg.policy, next_delay=arg.next_delay, abort=exc.message)
        return RetryOut(policy=retried.policy, next_delay=retried.next_delay)

    # --- remote agents (R7.3) ----------------------------------------------------------

    @activity.defn(name=ActivityName.RUN_REMOTE_AGENT_TURN.value)
    async def run_remote_agent_turn(self, arg: RemoteTurnIn) -> RemoteTurnOut:
        """One message to the remote agent; its stream runs until a final event."""
        registry = self.engine.registry
        try:
            agent = await registry.get(
                EntityRef(kind=EntityKind.AGENT, id=arg.agent, version="*"), Agent
            )
        except TinyHarnessError as exc:
            raise _translate(exc) from exc
        message = Message()
        message.CopyFrom(arg.message)
        if arg.remote_task_id:
            message.task_id = arg.remote_task_id
        else:
            message.ClearField("task_id")
        out = await _heartbeating(_remote_turn(agent, message), every=self.heartbeat_every)
        # The remote agent's text is recorded in history and relayed to the parent: scrub
        # it like every other activity result (abuse case 6); this activity runs outside
        # the operation runner, which scrubs the others.
        return self.engine.runner.redactor.scrub(out)

    # --- heartbeat (R16) --------------------------------------------------------------

    @activity.defn(name=ActivityName.POLL_CHANNELS.value)
    async def poll_channels(self, arg: PollIn) -> PollOut:
        """Forward every message waiting on a pull channel to its task's inbox (R16.1)."""
        forwarded = 0
        polled = 0
        registry = self.engine.registry
        for ref in registry.list(EntityKind.CHANNEL):
            channel = await registry.get(ref, Channel)
            if not channel.pull:
                continue
            polled += 1
            async for message in channel.receive():
                if self.client is None:
                    continue
                handle = self.client.get_workflow_handle(channel.task_id)
                try:
                    await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
                        "inbox", channel_to_a2a(channel, message), result_type=InboxReceipt
                    )
                except RPCError, WorkflowUpdateFailedError:
                    continue  # the task is gone or closed; the message stays recorded
                forwarded += 1
        return PollOut(forwarded=forwarded, channels=polled)

    @activity.defn(name=ActivityName.MONITOR_SNAPSHOT.value)
    async def monitor_snapshot(self, arg: MonitorIn) -> MonitorSnapshot:
        """The inner layer's view for the API layer and the ``heartbeat.tick`` hooks (R16.3)."""
        tasks: list[TaskMonitor] = []
        if self.client is not None:
            for execution_id in await running_task_workflows(self.client):
                handle = self.client.get_workflow_handle(execution_id)
                try:
                    tasks.append(await handle.query("monitor", result_type=TaskMonitor))
                except RPCError:
                    continue
        snapshot = MonitorSnapshot(
            at=datetime.now(UTC).isoformat(),
            tasks=tuple(tasks),
            pending_help=sum(1 for t in tasks if t.pending_help),
            queued_messages=sum(t.mailbox for t in tasks),
        )
        ctx = await self.engine.hooks.run(
            HookPoint(operation=Operation.HEARTBEAT_TICK, phase=Phase.PRE),
            HeartbeatTickPre(
                task_id="heartbeat", correlation_id=arg.correlation_id, snapshot=snapshot
            ),
        )
        self.last_snapshot = ctx.snapshot
        return ctx.snapshot

    @activity.defn(name=ActivityName.RETENTION_SWEEP.value)
    async def retention_sweep(self, arg: SweepIn) -> SweepOut:
        deleted = await self.engine.store.sweep(self.retention, datetime.now(UTC))
        return SweepOut(deleted={k.value: v for k, v in deleted.items()})


def ui_action_of(message: Message) -> Action | None:
    """The A2UI client message in an inbound A2A message, validated; ``None`` if none."""
    for part in message.parts:
        if part.HasField("data") and part.media_type == A2UI_MEDIA_TYPE:
            payload = cast(JsonObject, json_format.MessageToDict(part.data))
            parsed = parse_client_message(payload)
            if isinstance(parsed, Action):
                return parsed
            return None
    return None


def describe_action(action: Action) -> str:
    context = json.dumps(action.context, sort_keys=True)
    return (
        f"[A2UI action] {action.name} on surface {action.surface_id} "
        f"from {action.source_component_id}: {context}"
    )


async def _remote_turn(agent: Agent, message: Message) -> RemoteTurnOut:
    remote_task_id = message.task_id or ""
    state = TaskState.TASK_STATE_SUBMITTED
    text = ""
    async for event in agent.send_message(message, extensions=SUPPORTED_EXTENSIONS):
        if isinstance(event, Task):
            remote_task_id = event.id
            state = event.status.state
            if event.status.HasField("message"):
                text = "\n".join(p.text for p in event.status.message.parts if p.HasField("text"))
        elif isinstance(event, TaskStatusUpdateEvent):
            remote_task_id = event.task_id or remote_task_id
            state = event.status.state
            if event.status.HasField("message"):
                text = "\n".join(p.text for p in event.status.message.parts if p.HasField("text"))
        elif isinstance(event, Message):
            text = "\n".join(p.text for p in event.parts if p.HasField("text"))
        activity.heartbeat()
    name = TaskState.Name(state).removeprefix("TASK_STATE_")
    return RemoteTurnOut(
        remote_task_id=remote_task_id,
        state_name=name,
        text=text,
        final=state in TERMINAL,
    )


async def running_task_workflows(client: Client) -> list[str]:
    """Ids of the running ``TaskWorkflow`` executions: a visibility query, or an
    unfiltered list filtered here where the server supports no query (the test server)."""
    query = "WorkflowType = 'TaskWorkflow' AND ExecutionStatus = 'Running'"
    try:
        return [e.id async for e in client.list_workflows(query)]
    except RPCError:
        pass
    found: list[str] = []
    try:
        async for execution in client.list_workflows():
            if (
                execution.workflow_type == "TaskWorkflow"
                and execution.status is WorkflowExecutionStatus.RUNNING
            ):
                found.append(execution.id)
    except RPCError:
        return []
    return found


def channel_to_a2a(channel: Channel, message: ChannelMessage) -> Message:
    """A channel message as the A2A message the inbox accepts (channel extension part)."""
    data = ChannelMessageData(
        channel_id=channel.id,
        sender=message.sender,
        kind=message.kind,
        text=message.text,
        parts=message.parts,
    )
    value = struct_pb2.Value()
    value.struct_value.update(data.model_dump(mode="json"))
    msg = Message(
        message_id=message.id,
        task_id=channel.task_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(text=message.text), Part(data=value, media_type=CHANNEL_EXT_MEDIA_TYPE)],
    )
    msg.metadata.update({"participant_id": message.sender})
    return msg


__all__ = [
    "HEARTBEAT_EVERY",
    "NON_RETRYABLE_CODES",
    "Activities",
    "EventSink",
    "channel_to_a2a",
    "running_task_workflows",
]
