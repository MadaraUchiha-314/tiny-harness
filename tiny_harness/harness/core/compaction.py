"""Compaction (R10.4-R10.8): three replaceable policies, run before every LLM call.

``compaction.trigger.in`` decides whether the window is over budget (default: the
context manager's fraction of the smaller of the model window and the turn budget),
``compaction.keep.in`` names the sections that survive (default: the never-compact set
plus every loaded skill), and ``compaction.summarise.in`` replaces the oldest half of the
history with a summary (default: an LLM call). Each is an ``in`` hook point: the
built-in plugin registers the default body at priority 1000, so a plugin that sets
``result`` earlier wins. Every compaction leaves a ``CompactionRecord`` naming what it
removed, so a reviewer can audit the loss.

Media (issue-38 R6.2, design critic 7): the summarise request carries the folded media
the model can take, resolved to bytes inside the call; the rest is rendered as text, and
native audio is transcribed first where speech-to-text exists. Whatever summarises, the
summary is checked to name every folded media item in one line, and a missing line is
appended, so no image or recording drops out of the conversation unnamed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel

from tiny_harness.config import ReasoningEffort
from tiny_harness.errors import TinyHarnessError
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
from tiny_harness.harness.media.models import MediaAttachment, MediaKind, MediaRef
from tiny_harness.harness.media.render import resolve_media
from tiny_harness.harness.media.store import MediaStore
from tiny_harness.harness.models import (
    LLM,
    LLMModelInfo,
    LLMRequest,
    MessageItem,
    Role,
    SpeechToText,
    ToolCallItem,
)

log = logging.getLogger("tiny_harness.compaction")

TRIGGER = HookPoint(operation=Operation.COMPACTION_TRIGGER, phase=Phase.IN)
KEEP = HookPoint(operation=Operation.COMPACTION_KEEP, phase=Phase.IN)
SUMMARISE = HookPoint(operation=Operation.COMPACTION_SUMMARISE, phase=Phase.IN)

SUMMARISER_INSTRUCTIONS = (
    "You compact an agent's conversation history. Write a dense summary of the exchange "
    "below that preserves every fact, decision, identifier, number and open question the "
    "agent still needs; omit pleasantries. Output the summary only."
)
MEDIA_INSTRUCTIONS = (
    "The exchange holds media; the media attached to this message is in the order the "
    "exchange lists it. For every media item write exactly one line in the summary: "
    '[image <id> "<name>": <one-sentence description>] for an image, and '
    '[audio <id> "<name>": <transcript, or a one-sentence description>] for audio.'
)


@dataclass(frozen=True)
class CompactionMedia:
    """What compaction needs to carry media: the store the bytes are read from, the
    model's modalities for a model name, and speech-to-text WHERE it is configured."""

    store: MediaStore
    model_info: Callable[[str | None], LLMModelInfo]
    speech_to_text: SpeechToText | None = None
    max_bytes: int | None = None  # [media] max_request_media_bytes


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
    """``history`` is the text of the entries to compact; ``result`` the replacement summary.
    ``folded_media`` is every media item those entries hold, ``media`` the ones the model
    can take, as references (issue-38): the default body resolves them for the call."""

    previous_summary: str
    history: str
    removed_ids: tuple[int, ...]
    folded_media: tuple[MediaRef, ...] = ()
    media: tuple[MediaAttachment, ...] = ()
    model: str | None = None  # the task's settings: the summary is one of its model calls
    reasoning_effort: ReasoningEffort | None = None
    result: str | None = None


def media_name(ref: MediaRef) -> str:
    return ref.name or ref.id


def render_media(attachment: MediaAttachment, *, carried: bool = False) -> str:
    """One folded media item as the summariser reads it: a pointer to the attached media
    when the request carries it, else its description as text."""
    ref = attachment.ref
    name = media_name(ref)
    if carried:
        return f'(attached: {ref.kind.value} {ref.id} "{name}")'
    if ref.kind is MediaKind.IMAGE:
        size = (
            f", {ref.width}\N{MULTIPLICATION SIGN}{ref.height}" if ref.width and ref.height else ""
        )
        return f"[image: {name}{size}, media {ref.id}]"
    seconds = f", {round(ref.duration_ms / 1000)} s" if ref.duration_ms is not None else ""
    if attachment.transcript is None:
        return f"[audio: {name}{seconds}, no transcript, media {ref.id}]"
    return f'[audio: {name}{seconds}, transcript: "{attachment.transcript}"] (media {ref.id})'


def render_entries(
    entries: tuple[HistoryEntry, ...],
    *,
    carried: Collection[str] = (),
    media: Mapping[str, MediaAttachment] | None = None,
) -> str:
    """The entries as the summariser reads them. ``carried`` names the media ids the
    request carries; ``media`` replaces attachments by id (one transcribed for this)."""
    lines: list[str] = []
    for entry in entries:
        item = entry.item
        if isinstance(item, MessageItem):
            lines.append(f"[{entry.id}] {item.role.value}: {item.text}")
            for attachment in item.media:
                attachment = (media or {}).get(attachment.ref.id, attachment)
                lines.append("  " + render_media(attachment, carried=attachment.ref.id in carried))
        elif isinstance(item, ToolCallItem):
            lines.append(f"[{entry.id}] call {item.call.name}({item.call.arguments})")
        else:
            text = " ".join(p.text or str(p.data or "") for p in item.result.content)
            lines.append(f"[{entry.id}] result: {text}")
    return "\n".join(lines)


def folded_media(entries: tuple[HistoryEntry, ...]) -> list[MediaAttachment]:
    """Every media item of ``entries``, once each, in order."""
    seen: dict[str, MediaAttachment] = {}
    for entry in entries:
        item = entry.item
        if isinstance(item, MessageItem):
            for attachment in item.media:
                seen.setdefault(attachment.ref.id, attachment)
    return list(seen.values())


def media_line(attachment: MediaAttachment) -> str:
    """The line a summary names a media item with when the summariser did not."""
    ref = attachment.ref
    detail = attachment.transcript if attachment.transcript else "not described"
    return f'[{ref.kind.value} {ref.id} "{media_name(ref)}": {detail}]'


def named_media(summary: str, media: Collection[MediaAttachment]) -> str:
    """``summary`` with a line for every media item it does not name (R6.2)."""
    missing = [
        media_line(a)
        for a in media
        if f"[{a.ref.kind.value} {a.ref.id} " not in summary
        and f"[{a.ref.kind.value} {a.ref.id}:" not in summary
    ]
    if not missing:
        return summary
    return "\n".join([summary, *missing]) if summary else "\n".join(missing)


class Compactor:
    """Runs the three policies; ``maybe_compact`` is called before every LLM call."""

    def __init__(
        self,
        *,
        hooks: HookManager,
        manager: ContextWindowManager,
        llm: LLM,
        now: type[datetime] = datetime,
        media: CompactionMedia | None = None,
    ) -> None:
        self._hooks = hooks
        self._manager = manager
        self._llm = llm
        self._now = now
        self._media = media

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
            instructions = SUMMARISER_INSTRUCTIONS
            if ctx.folded_media:
                instructions = f"{instructions}\n{MEDIA_INSTRUCTIONS}"
            request = LLMRequest(
                instructions=instructions,
                input=(
                    MessageItem(
                        role=Role.USER,
                        text=f"{prior}Exchange:\n{ctx.history}",
                        media=ctx.media,
                    ),
                ),
                model=ctx.model,
                reasoning_effort=ctx.reasoning_effort,
            )
            media = self._media
            if media is not None and ctx.media:
                # Bytes only here, inside the call: never in the hook context (issue-38).
                request = await resolve_media(
                    request, media.store, media.model_info(ctx.model), max_bytes=media.max_bytes
                )
            response = await llm.invoke(request)
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
        media = await self._prepare_media(folded_media(removed))
        carried = self._carried(media, window.model)
        summary_ctx = await self._hooks.run(
            SUMMARISE,
            CompactionSummariseIn(
                task_id=task_id,
                correlation_id=correlation_id,
                previous_summary=state.summary,
                history=render_entries(
                    removed,
                    carried={a.ref.id for a in carried},
                    media={a.ref.id: a for a in media},
                ),
                removed_ids=tuple(e.id for e in removed),
                folded_media=tuple(a.ref for a in media),
                media=carried,
                model=window.model,
                reasoning_effort=window.reasoning_effort,
            ),
        )
        summary = named_media(summary_ctx.result or state.summary, media)
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

    async def _prepare_media(self, media: list[MediaAttachment]) -> list[MediaAttachment]:
        """Native audio with no transcript, transcribed first WHERE speech-to-text exists
        (design critic 7); a failure leaves it as it was."""
        helper = self._media
        if helper is None or helper.speech_to_text is None:
            return media
        stt = helper.speech_to_text
        prepared: list[MediaAttachment] = []
        for attachment in media:
            ref = attachment.ref
            if ref.kind is MediaKind.AUDIO and attachment.transcript is None:
                try:
                    audio = await helper.store.get(ref)
                    transcript = await stt.transcribe(
                        audio, media_type=ref.media_type, name=ref.name or "audio"
                    )
                    attachment = MediaAttachment(ref=ref, transcript=transcript.text)
                except (FileNotFoundError, TinyHarnessError) as exc:
                    log.warning(
                        "audio not transcribed for compaction",
                        extra={"media_id": ref.id, "error": type(exc).__name__},
                    )
            prepared.append(attachment)
        return prepared

    def _carried(
        self, media: list[MediaAttachment], model: str | None
    ) -> tuple[MediaAttachment, ...]:
        """The folded media the summary request carries: what the model takes (images,
        and native audio of a type it takes), WHERE a store can resolve it."""
        helper = self._media
        if helper is None or not media:
            return ()
        info = helper.model_info(model)
        images = "image" in info.input_modalities
        audio = "audio" in info.input_modalities
        return tuple(
            MediaAttachment(ref=a.ref)
            for a in media
            if (a.ref.kind is MediaKind.IMAGE and images)
            or (
                a.ref.kind is MediaKind.AUDIO
                and a.transcript is None
                and audio
                and a.ref.media_type in info.audio_input_formats
            )
        )


__all__ = [
    "KEEP",
    "MEDIA_INSTRUCTIONS",
    "SUMMARISE",
    "SUMMARISER_INSTRUCTIONS",
    "TRIGGER",
    "CompactionKeepIn",
    "CompactionMedia",
    "CompactionRecord",
    "CompactionSummariseIn",
    "CompactionTriggerIn",
    "Compactor",
    "folded_media",
    "media_line",
    "named_media",
    "render_entries",
    "render_media",
]
