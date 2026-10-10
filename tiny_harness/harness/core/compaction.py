"""Compaction (R10.4-R10.8): three replaceable policies, run before every LLM call.

``compaction.trigger.in`` decides whether the window is over budget (default: the
context manager's fraction of the smaller of the model window and the turn budget),
``compaction.keep.in`` names the sections that survive (default: the never-compact set
plus every loaded skill), and ``compaction.summarise.in`` replaces the oldest half of the
history with a summary (default: an LLM call). Each is an ``in`` hook point: the
built-in plugin registers the default body at priority 1000, so a plugin that sets
``result`` earlier wins. Every compaction leaves a ``CompactionRecord`` naming what it
removed, so a reviewer can audit the loss.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from tiny_harness.harness.core.context import NEVER_COMPACT, ContextWindow, ContextWindowManager
from tiny_harness.harness.core.state import AgentState, HistoryEntry
from tiny_harness.harness.hooks import (
    DEFAULT_BODY_PRIORITY,
    FunctionExecutor,
    HookContext,
    HookManager,
    HookPoint,
    Operation,
    Phase,
)
from tiny_harness.harness.models import (
    LLM,
    LLMModelInfo,
    LLMRequest,
    MessageItem,
    Role,
    ToolCallItem,
)

TRIGGER = HookPoint(operation=Operation.COMPACTION_TRIGGER, phase=Phase.IN)
KEEP = HookPoint(operation=Operation.COMPACTION_KEEP, phase=Phase.IN)
SUMMARISE = HookPoint(operation=Operation.COMPACTION_SUMMARISE, phase=Phase.IN)

SUMMARISER_INSTRUCTIONS = (
    "You compact an agent's conversation history. Write a dense summary of the exchange "
    "below that preserves every fact, decision, identifier, number and open question the "
    "agent still needs; omit pleasantries. Output the summary only."
)


class CompactionRecord(BaseModel, frozen=True):
    """What one compaction removed and what replaced it (R10.6)."""

    task_id: str
    turn: int
    removed_ids: tuple[int, ...]
    summary: str
    tokens_before: int
    tokens_after: int
    at: datetime


class CompactionTriggerIn(HookContext):
    estimated_tokens: int
    budget: int
    fraction: float
    result: bool | None = None


class CompactionKeepIn(HookContext):
    sections: tuple[str, ...]
    result: tuple[str, ...] | None = None


class CompactionSummariseIn(HookContext):
    """``history`` is the text of the entries to compact; ``result`` the replacement summary."""

    previous_summary: str
    history: str
    removed_ids: tuple[int, ...]
    result: str | None = None


def render_entries(entries: tuple[HistoryEntry, ...]) -> str:
    lines: list[str] = []
    for entry in entries:
        item = entry.item
        if isinstance(item, MessageItem):
            lines.append(f"[{entry.id}] {item.role.value}: {item.text}")
        elif isinstance(item, ToolCallItem):
            lines.append(f"[{entry.id}] call {item.call.name}({item.call.arguments})")
        else:
            text = " ".join(p.text or str(p.data or "") for p in item.result.content)
            lines.append(f"[{entry.id}] result: {text}")
    return "\n".join(lines)


class Compactor:
    """Runs the three policies; ``maybe_compact`` is called before every LLM call."""

    def __init__(
        self,
        *,
        hooks: HookManager,
        manager: ContextWindowManager,
        llm: LLM,
        now: type[datetime] = datetime,
    ) -> None:
        self._hooks = hooks
        self._manager = manager
        self._llm = llm
        self._now = now

    def register_defaults(self) -> None:
        """The built-in bodies, at the default priority so any plugin can override them."""
        manager = self._manager
        llm = self._llm

        async def trigger(point: HookPoint, ctx: HookContext) -> HookContext | None:
            assert isinstance(ctx, CompactionTriggerIn)
            if ctx.result is not None:
                return None
            return ctx.model_copy(
                update={"result": ctx.estimated_tokens > ctx.fraction * ctx.budget}
            )

        async def keep(point: HookPoint, ctx: HookContext) -> HookContext | None:
            assert isinstance(ctx, CompactionKeepIn)
            if ctx.result is not None:
                return None
            kept = tuple(s for s in ctx.sections if s in NEVER_COMPACT or s.startswith("skill:"))
            return ctx.model_copy(update={"result": kept})

        async def summarise(point: HookPoint, ctx: HookContext) -> HookContext | None:
            assert isinstance(ctx, CompactionSummariseIn)
            if ctx.result is not None:
                return None
            prior = f"Previous summary:\n{ctx.previous_summary}\n\n" if ctx.previous_summary else ""
            response = await llm.invoke(
                LLMRequest(
                    instructions=SUMMARISER_INSTRUCTIONS,
                    input=(MessageItem(role=Role.USER, text=f"{prior}Exchange:\n{ctx.history}"),),
                )
            )
            return ctx.model_copy(update={"result": response.output_text.strip()})

        del manager
        self._hooks.register(
            FunctionExecutor(
                "compaction.trigger", trigger, priority=DEFAULT_BODY_PRIORITY, points=[TRIGGER]
            )
        )
        self._hooks.register(
            FunctionExecutor("compaction.keep", keep, priority=DEFAULT_BODY_PRIORITY, points=[KEEP])
        )
        self._hooks.register(
            FunctionExecutor(
                "compaction.summarise",
                summarise,
                priority=DEFAULT_BODY_PRIORITY,
                points=[SUMMARISE],
            )
        )

    async def should_compact(
        self, window: ContextWindow, model: LLMModelInfo, *, task_id: str, correlation_id: str
    ) -> bool:
        ctx = CompactionTriggerIn(
            task_id=task_id,
            correlation_id=correlation_id,
            estimated_tokens=window.estimated_tokens,
            budget=self._manager.budget(model),
            fraction=self._manager.compaction_fraction,
        )
        out = await self._hooks.run(TRIGGER, ctx)
        return bool(out.result)

    async def compact(
        self, state: AgentState, window: ContextWindow, *, task_id: str, correlation_id: str
    ) -> tuple[AgentState, CompactionRecord]:
        keep_ctx = await self._hooks.run(
            KEEP,
            CompactionKeepIn(
                task_id=task_id,
                correlation_id=correlation_id,
                sections=tuple(s.name for s in window.sections),
            ),
        )
        kept = set(keep_ctx.result or ())
        # Sections in the keep set are untouched by construction: compaction only ever
        # rewrites the history and the state summary.
        assert kept >= {s.name for s in window.sections if s.never_compact}
        history = state.history
        cut = max(len(history) // 2, 1) if history else 0
        removed, remaining = history[:cut], history[cut:]
        summary_ctx = await self._hooks.run(
            SUMMARISE,
            CompactionSummariseIn(
                task_id=task_id,
                correlation_id=correlation_id,
                previous_summary=state.summary,
                history=render_entries(removed),
                removed_ids=tuple(e.id for e in removed),
            ),
        )
        summary = summary_ctx.result or state.summary
        new_state = state.model_copy(update={"history": remaining, "summary": summary})
        removed_chars = sum(len(render_entries((e,))) for e in removed)
        tokens_after = max(window.estimated_tokens - removed_chars // 4 + len(summary) // 4, 0)
        record = CompactionRecord(
            task_id=task_id,
            turn=state.turn,
            removed_ids=tuple(e.id for e in removed),
            summary=summary,
            tokens_before=window.estimated_tokens,
            tokens_after=tokens_after,
            at=self._now.now(UTC),
        )
        return new_state, record


__all__ = [
    "KEEP",
    "SUMMARISE",
    "SUMMARISER_INSTRUCTIONS",
    "TRIGGER",
    "CompactionKeepIn",
    "CompactionRecord",
    "CompactionSummariseIn",
    "CompactionTriggerIn",
    "Compactor",
    "render_entries",
]
