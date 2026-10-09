"""An in-process ``Operations`` host for the core loop (Layer 4).

It wires the context window manager, the compactor, the LLM, the validating invoker over
the registry (with the core intrinsics bound to the current task), the hook-wrapped
operation runner and the store. Layer 5 binds the same loop to Temporal activities;
here sub-tasks are recorded as references only, and nothing runs them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from tiny_harness.harness.core.compaction import CompactionRecord, Compactor
from tiny_harness.harness.core.context import ContextWindow, ContextWindowManager
from tiny_harness.harness.core.intrinsics import TaskContext, core_intrinsics
from tiny_harness.harness.core.loop import (
    LLMInvokedPost,
    LLMInvokedPre,
    RequestReceivedPost,
    RequestReceivedPre,
    SubtaskSpawnedPost,
    SubtaskSpawnedPre,
    TaskCompleteIn,
    ToolCallsExtractedPre,
    ToolInvokedPost,
    ToolInvokedPre,
    default_completion,
)
from tiny_harness.harness.core.state import AgentState
from tiny_harness.harness.core.task import HarnessTask, TaskRef
from tiny_harness.harness.entities import EntityKind, Registry, RegistryEntry
from tiny_harness.harness.hooks import (
    DEFAULT_BODY_PRIORITY,
    FunctionExecutor,
    HookContext,
    HookManager,
    HookPoint,
    Operation,
    OperationRunner,
    Phase,
)
from tiny_harness.harness.models import (
    LLM,
    LLMRequest,
    LLMResponse,
    MessageItem,
    Role,
    extract_tool_calls,
)
from tiny_harness.harness.persistence import (
    CompactionStoreRecord,
    PlanRecord,
    StateRecord,
    Store,
    TaskRecord,
)
from tiny_harness.harness.security import Redactor
from tiny_harness.harness.tools import (
    Tool,
    ToolCall,
    ToolDefinition,
    ToolInvoker,
    ToolResult,
    WorkflowCommand,
)

TASK_COMPLETE = HookPoint(operation=Operation.TASK_COMPLETE, phase=Phase.IN)


def register_completion_default(hooks: HookManager) -> None:
    """The built-in ``task.complete.in`` body at the default priority (R8.5)."""

    async def body(point: HookPoint, ctx: HookContext) -> HookContext | None:
        assert isinstance(ctx, TaskCompleteIn)
        if ctx.result is not None:
            return None
        return ctx.model_copy(update={"result": default_completion(ctx.unresolved)})

    hooks.register(
        FunctionExecutor(
            "task.complete", body, priority=DEFAULT_BODY_PRIORITY, points=[TASK_COMPLETE]
        )
    )


class InProcessOperations:
    """The loop's host for one process: every operation is hook-wrapped and redacted."""

    def __init__(
        self,
        *,
        registry: Registry,
        hooks: HookManager,
        llm: LLM,
        store: Store,
        system_prompt: str,
        skills_index: str = "",
        manager: ContextWindowManager | None = None,
        redactor: Redactor | None = None,
        correlation_id: str = "local",
        actor: str | None = None,
    ) -> None:
        self.registry = registry
        self.hooks = hooks
        self.llm = llm
        self.store = store
        self.system_prompt = system_prompt
        self.skills_index = skills_index
        self.manager = manager or ContextWindowManager()
        self.compactor = Compactor(hooks=hooks, manager=self.manager, llm=llm)
        self.runner = OperationRunner(hooks, redactor)
        self.invoker = ToolInvoker(registry)
        self.correlation_id = correlation_id
        self.context = TaskContext(actor=actor)
        self.spawned: list[tuple[TaskRef, WorkflowCommand]] = []
        self.resolved_children: set[str] = set()
        self._bound = False

    async def bind(self) -> None:
        """Register the core intrinsics and the default ``in`` bodies; idempotent."""
        if self._bound:
            return
        for tool in core_intrinsics(self.context):
            await self.registry.add(RegistryEntry(ref=tool.ref, instance=tool), override=True)
        self.compactor.register_defaults()
        register_completion_default(self.hooks)
        self._bound = True

    def _ctx(self, task: HarnessTask) -> TaskContext:
        self.context.task = task
        return self.context

    async def ingest(self, task: HarnessTask, state: AgentState, text: str) -> AgentState:
        pre = RequestReceivedPre(task_id=task.id, correlation_id=self.correlation_id, text=text)

        async def body(ctx: RequestReceivedPre) -> AgentState:
            return state.append(MessageItem(role=Role.USER, text=ctx.text))

        return await self.runner.run(
            Operation.REQUEST_RECEIVED,
            pre,
            body,
            make_post=lambda p, out: RequestReceivedPost(
                task_id=p.task_id, correlation_id=p.correlation_id, text=p.text, state=out
            ),
            extract=lambda post: post.state,
        )

    async def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        definitions: list[ToolDefinition] = []
        for ref in self.registry.list(EntityKind.TOOL):
            tool = await self.registry.get(ref, Tool)
            definitions.append(tool.definition)
        return tuple(definitions)

    async def assemble(self, task: HarnessTask, state: AgentState) -> ContextWindow:
        self._ctx(task)
        return self.manager.assemble(
            task=task,
            state=state,
            system_prompt=self.system_prompt,
            skills_index=self.skills_index,
            tools=await self.tool_definitions(),
        )

    async def should_compact(self, task: HarnessTask, window: ContextWindow) -> bool:
        return await self.compactor.should_compact(
            window, self.llm.info, task_id=task.id, correlation_id=self.correlation_id
        )

    async def compact(
        self, task: HarnessTask, state: AgentState, window: ContextWindow
    ) -> tuple[AgentState, CompactionRecord]:
        return await self.compactor.compact(
            state, window, task_id=task.id, correlation_id=self.correlation_id
        )

    async def invoke_llm(self, task: HarnessTask, request: LLMRequest) -> LLMResponse:
        pre = LLMInvokedPre(task_id=task.id, correlation_id=self.correlation_id, request=request)

        async def body(ctx: LLMInvokedPre) -> LLMResponse:
            return await self.llm.invoke(ctx.request)

        return await self.runner.run(
            Operation.LLM_INVOKED,
            pre,
            body,
            make_post=lambda p, out: LLMInvokedPost(
                task_id=p.task_id, correlation_id=p.correlation_id, request=p.request, response=out
            ),
            extract=lambda post: post.response,
        )

    async def extract(self, task: HarnessTask, response: LLMResponse) -> tuple[ToolCall, ...]:
        ctx = await self.hooks.run(
            HookPoint(operation=Operation.TOOL_CALLS_EXTRACTED, phase=Phase.PRE),
            ToolCallsExtractedPre(
                task_id=task.id,
                correlation_id=self.correlation_id,
                response=response,
                calls=extract_tool_calls(response),
            ),
        )
        return ctx.calls

    async def invoke_tool(self, task: HarnessTask, call: ToolCall) -> ToolResult | WorkflowCommand:
        self._ctx(task)
        pre = ToolInvokedPre(task_id=task.id, correlation_id=self.correlation_id, call=call)

        async def body(ctx: ToolInvokedPre) -> ToolResult | WorkflowCommand:
            return await self.invoker.invoke(ctx.call)

        return await self.runner.run(
            Operation.TOOL_INVOKED,
            pre,
            body,
            make_post=lambda p, out: ToolInvokedPost(
                task_id=p.task_id, correlation_id=p.correlation_id, call=p.call, result=out
            ),
            extract=lambda post: post.result,
        )

    async def decide_completion(self, task: HarnessTask) -> TaskCompleteIn:
        unresolved = tuple(t for t in task.ext.sub_tasks if t.task_id not in self.resolved_children)
        ctx = TaskCompleteIn(
            task_id=task.id, correlation_id=self.correlation_id, unresolved=unresolved
        )
        return await self.runner.run_in(Operation.TASK_COMPLETE, ctx)

    async def spawn(self, task: HarnessTask, command: WorkflowCommand) -> TaskRef:
        parent = TaskRef(task_id=task.id)
        pre = SubtaskSpawnedPre(
            task_id=task.id, correlation_id=self.correlation_id, parent=parent, command=command
        )

        async def body(ctx: SubtaskSpawnedPre) -> TaskRef:
            child = TaskRef(task_id=f"{task.id}.{uuid.uuid4().hex[:8]}")
            self.spawned.append((child, ctx.command))
            return child

        return await self.runner.run(
            Operation.SUBTASK_SPAWNED,
            pre,
            body,
            make_post=lambda p, out: SubtaskSpawnedPost(
                task_id=p.task_id,
                correlation_id=p.correlation_id,
                parent=p.parent,
                command=p.command,
                child=out,
            ),
            extract=lambda post: post.child,
        )

    async def record(
        self, task: HarnessTask, state: AgentState, compaction: CompactionRecord | None
    ) -> None:
        now = datetime.now(UTC)
        await self.store.put(
            TaskRecord(
                id=task.id,
                context_id=task.context_id,
                task_id=task.id,
                created_at=now,
                task=task.proto,
                state_name=task.state_name,
            )
        )
        if task.ext.plan is not None:
            await self.store.put(
                PlanRecord(
                    id=f"{task.id}:{state.turn}",
                    context_id=task.context_id,
                    task_id=task.id,
                    created_at=now,
                    plan=task.ext.plan,
                    turn=state.turn,
                )
            )
        await self.store.put(StateRecord.from_state(state, context_id=task.context_id, at=now))
        if compaction is not None:
            await self.store.put(
                CompactionStoreRecord(
                    id=f"{task.id}:{compaction.turn}",
                    context_id=task.context_id,
                    task_id=task.id,
                    created_at=now,
                    record=compaction,
                )
            )

    async def set_state(self, task: HarnessTask, state: int) -> HarnessTask:
        updated = task.with_state(state)
        self._ctx(updated)
        return updated


__all__ = ["TASK_COMPLETE", "InProcessOperations", "register_completion_default"]
