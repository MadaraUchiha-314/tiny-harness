"""The core loop (decision-004, R8.4, R8.5, R12.2, R12.5): the ticket's pseudo-code.

    while True:
        ctx = assemble(state)            # compact first if over budget
        response = invoke_llm(ctx)
        calls = extract_tool_calls(response)
        if not calls: break              # then the completion predicate
        execute(calls)                   # each through the validating invoker

The loop runs over an ``Operations`` port so the same code drives the in-process host
(tests, Layer 4) and the Temporal workflow (Layer 5, where every operation is an
activity). Everything the LLM can make the harness do is a tool call; an intrinsic's
``WorkflowCommand`` is applied here with no I/O. ``ask_participant`` ends the run in
``INPUT_REQUIRED``; the next call with the reply resumes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from a2a.types import TaskState

from tiny_harness.harness.core.compaction import CompactionRecord
from tiny_harness.harness.core.context import ContextWindow
from tiny_harness.harness.core.intrinsics import apply_to_task, link_subtask
from tiny_harness.harness.core.state import AgentState, LoadedSkillRecord
from tiny_harness.harness.core.task import HarnessTask, TaskRef
from tiny_harness.harness.hooks import HookContext
from tiny_harness.harness.models import (
    LLMRequest,
    LLMResponse,
    MessageItem,
    Role,
    ToolCallItem,
    ToolResultItem,
)
from tiny_harness.harness.tools import ToolCall, ToolResult, WorkflowCommand
from tiny_harness.jsontypes import JsonObject


class RequestReceivedPre(HookContext):
    """An inbound message, scrubbed before any executor or the history sees it."""

    text: str


class RequestReceivedPost(RequestReceivedPre):
    state: AgentState


class LLMInvokedPre(HookContext):
    request: LLMRequest


class LLMInvokedPost(LLMInvokedPre):
    response: LLMResponse


class ToolCallsExtractedPre(HookContext):
    response: LLMResponse
    calls: tuple[ToolCall, ...]


class ToolInvokedPre(HookContext):
    """One call; an executor rewrites it or raises ``HookAbort`` to veto it (R2.9)."""

    call: ToolCall


class ToolInvokedPost(ToolInvokedPre):
    result: ToolResult | WorkflowCommand


class CompletionDecision(StrEnum):
    WAIT = "wait"
    COMPLETE = "complete"
    FAIL = "fail"


class TaskCompleteIn(HookContext):
    """``task.complete.in``: the default body waits while a sub-task is unresolved (R8.5)."""

    unresolved: tuple[TaskRef, ...]
    result: CompletionDecision | None = None
    reason: str = ""


class SubtaskSpawnedPre(HookContext):
    parent: TaskRef
    command: WorkflowCommand


class SubtaskSpawnedPost(SubtaskSpawnedPre):
    child: TaskRef


type OutcomeKind = Literal["completed", "failed", "waiting_for_reply", "waiting_for_children"]


@dataclass(frozen=True)
class Outcome:
    """How one run of the loop ended; ``help`` is the pending ``ask_participant``."""

    kind: OutcomeKind
    task: HarnessTask
    state: AgentState
    final_text: str = ""
    help: JsonObject | None = None
    reason: str = ""


class Operations(Protocol):
    """What the loop needs from its host; every method is an activity in Layer 5."""

    async def ingest(self, task: HarnessTask, state: AgentState, text: str) -> AgentState: ...

    async def drain(self, task: HarnessTask, state: AgentState) -> AgentState:
        """Top of every turn: fold queued inbox items into the history (R15.3)."""
        ...

    async def assemble(self, task: HarnessTask, state: AgentState) -> ContextWindow: ...

    async def should_compact(self, task: HarnessTask, window: ContextWindow) -> bool: ...

    async def compact(
        self, task: HarnessTask, state: AgentState, window: ContextWindow
    ) -> tuple[AgentState, CompactionRecord]: ...

    async def invoke_llm(self, task: HarnessTask, request: LLMRequest) -> LLMResponse: ...

    async def extract(self, task: HarnessTask, response: LLMResponse) -> tuple[ToolCall, ...]: ...

    async def invoke_tool(
        self, task: HarnessTask, call: ToolCall
    ) -> ToolResult | WorkflowCommand: ...

    async def decide_completion(self, task: HarnessTask) -> TaskCompleteIn: ...

    async def spawn(self, task: HarnessTask, command: WorkflowCommand) -> TaskRef: ...

    async def record(
        self, task: HarnessTask, state: AgentState, compaction: CompactionRecord | None
    ) -> None: ...

    async def set_state(self, task: HarnessTask, state: int) -> HarnessTask: ...

    async def wait_for_reply(self, task: HarnessTask, help: JsonObject) -> HarnessTask:
        """``ask_participant``: deliver the question, then ``INPUT_REQUIRED`` (R12.2)."""
        ...

    async def complete(self, task: HarnessTask, text: str) -> HarnessTask: ...

    async def emit_ui(self, task: HarnessTask, command: WorkflowCommand) -> None:
        """``emit_ui``: deliver validated A2UI messages to the surfaces (R20.5)."""
        ...

    async def fail(self, task: HarnessTask, reason: str) -> HarnessTask: ...


def default_completion(unresolved: tuple[TaskRef, ...]) -> CompletionDecision:
    """The ``task.complete.in`` default body (R8.5): wait while a sub-task is unresolved."""
    return CompletionDecision.WAIT if unresolved else CompletionDecision.COMPLETE


def _skill_record(command: WorkflowCommand) -> LoadedSkillRecord:
    tools = command.payload.get("tools")
    names = tuple(str(t) for t in tools) if isinstance(tools, list) else ()
    return LoadedSkillRecord(
        name=str(command.payload["name"]), body=str(command.payload.get("body", "")), tools=names
    )


class CoreLoop:
    """Drives one task over an ``Operations`` host until it completes, fails or waits."""

    def __init__(self, ops: Operations, *, max_turns: int = 50) -> None:
        self._ops = ops
        self._max_turns = max_turns

    async def run(self, task: HarnessTask, state: AgentState, inbound: str | None) -> Outcome:
        ops = self._ops
        if inbound is not None:
            state = await ops.ingest(task, state, inbound)
        if task.state != TaskState.TASK_STATE_WORKING:
            task = await ops.set_state(task, TaskState.TASK_STATE_WORKING)
        for _ in range(self._max_turns):
            state = await ops.drain(task, state)
            window = await ops.assemble(task, state)
            compaction: CompactionRecord | None = None
            if await ops.should_compact(task, window):
                state, compaction = await ops.compact(task, state, window)
                window = await ops.assemble(task, state)
            response = await ops.invoke_llm(task, window.request(cache_key=task.id))
            calls = await ops.extract(task, response)
            if response.output_text:
                state = state.append(MessageItem(role=Role.ASSISTANT, text=response.output_text))
            state = state.after_turn(response.usage, window.chars)
            if not calls:
                await ops.record(task, state, compaction)
                return await self._finish(task, state, response.output_text)
            waiting: JsonObject | None = None
            for call in calls:
                state = state.append(ToolCallItem(call=call))
                out = await ops.invoke_tool(task, call)
                if isinstance(out, WorkflowCommand):
                    task, state, waiting = await self._apply(task, state, out, waiting)
                    out = out.result
                state = state.append(ToolResultItem(result=out))
            await ops.record(task, state, compaction)
            if waiting is not None:
                task = await ops.wait_for_reply(task, waiting)
                return Outcome(kind="waiting_for_reply", task=task, state=state, help=waiting)
        task = await ops.fail(task, "turn limit reached")
        return Outcome(kind="failed", task=task, state=state, reason="turn limit reached")

    async def _apply(
        self,
        task: HarnessTask,
        state: AgentState,
        command: WorkflowCommand,
        waiting: JsonObject | None,
    ) -> tuple[HarnessTask, AgentState, JsonObject | None]:
        if command.kind in ("attach_plan", "complete_step", "set_role"):
            return apply_to_task(task, command), state, waiting
        if command.kind == "skill_loaded":
            return task, state.with_skill(_skill_record(command)), waiting
        if command.kind == "skill_unloaded":
            return task, state.without_skill(str(command.payload["name"])), waiting
        if command.kind in ("spawn_subtask", "create_participant_task"):
            ref = await self._ops.spawn(task, command)
            step = command.payload.get("step")
            return link_subtask(task, ref, str(step) if step else None), state, waiting
        if command.kind == "wait_for_reply":
            return task, state, {**command.payload, "call_id": command.call_id}
        if command.kind == "ui_emitted":
            await self._ops.emit_ui(task, command)
        return task, state, waiting

    async def _finish(self, task: HarnessTask, state: AgentState, text: str) -> Outcome:
        decision = await self._ops.decide_completion(task)
        if decision.result is CompletionDecision.WAIT:
            return Outcome(kind="waiting_for_children", task=task, state=state, final_text=text)
        if decision.result is CompletionDecision.FAIL:
            task = await self._ops.fail(task, decision.reason)
            return Outcome(kind="failed", task=task, state=state, reason=decision.reason)
        task = await self._ops.complete(task, text)
        return Outcome(kind="completed", task=task, state=state, final_text=text)


__all__ = [
    "CompletionDecision",
    "CoreLoop",
    "LLMInvokedPost",
    "LLMInvokedPre",
    "Operations",
    "Outcome",
    "OutcomeKind",
    "RequestReceivedPost",
    "RequestReceivedPre",
    "SubtaskSpawnedPost",
    "SubtaskSpawnedPre",
    "TaskCompleteIn",
    "ToolCallsExtractedPre",
    "ToolInvokedPost",
    "ToolInvokedPre",
    "default_completion",
]
