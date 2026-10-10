"""Renderers (R20.1, R20.4, R20.7): what a surface can draw, and the typed placeholder for
what it cannot. ``RenderPlan`` is the renderer-neutral description a TUI or a web page
turns into widgets; MCP Apps (``text/html;profile=mcp-app``) can be declared in
``supported`` later without changing the interface."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Literal

from a2a.types import Message, Part, Task, TaskStatusUpdateEvent
from google.protobuf import json_format
from pydantic import BaseModel, ConfigDict

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef
from tiny_harness.jsontypes import JsonObject

TEXT_PLAIN = "text/plain"
type ItemKind = Literal["text", "status", "data", "placeholder"]


class RenderItem(BaseModel):
    """One thing to draw: text, a status change, a data part a renderer knows, or the
    placeholder naming the kind it does not (R20.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ItemKind
    media_type: str = TEXT_PLAIN
    text: str = ""
    data: JsonObject | None = None
    role: Literal["user", "agent", "system"] = "agent"


class RenderPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[RenderItem, ...] = ()

    @property
    def placeholders(self) -> tuple[RenderItem, ...]:
        return tuple(i for i in self.items if i.kind == "placeholder")


def part_media_type(part: Part) -> str:
    if part.HasField("text"):
        return TEXT_PLAIN
    return part.media_type or "application/octet-stream"


def plan_message(message: Message, supported: frozenset[str]) -> list[RenderItem]:
    role: Literal["user", "agent"] = "user" if message.role == 1 else "agent"
    items: list[RenderItem] = []
    for part in message.parts:
        media = part_media_type(part)
        if part.HasField("text") and TEXT_PLAIN in supported:
            items.append(RenderItem(kind="text", text=part.text, role=role))
        elif part.HasField("data") and media in supported:
            data = json_format.MessageToDict(part.data)
            items.append(RenderItem(kind="data", media_type=media, data=data, role=role))
        else:
            items.append(
                RenderItem(
                    kind="placeholder",
                    media_type=media,
                    text=f"[unrenderable part: {media}]",
                    role=role,
                )
            )
    return items


class Renderer(Entity):
    """A renderer entity: the media types it draws; everything else is a placeholder."""

    kind = EntityKind.RENDERER

    def __init__(self, ref: EntityRef, *, supported: Sequence[str]) -> None:
        super().__init__(ref)
        self.supported = frozenset(supported)

    def plan(self, event: A2AEvent) -> RenderPlan:
        """The renderer-neutral plan; subclasses draw it."""
        items: list[RenderItem] = []
        if isinstance(event, Message):
            items.extend(plan_message(event, self.supported))
        elif isinstance(event, Task | TaskStatusUpdateEvent):
            items.append(RenderItem(kind="status", text=_state_name(event.status.state)))
            if event.status.HasField("message"):
                items.extend(plan_message(event.status.message, self.supported))
        else:
            for part in event.artifact.parts:
                media = part_media_type(part)
                if part.HasField("text") and TEXT_PLAIN in self.supported:
                    items.append(RenderItem(kind="text", text=part.text))
                elif part.HasField("data") and media in self.supported:
                    data = json_format.MessageToDict(part.data)
                    items.append(RenderItem(kind="data", media_type=media, data=data))
                else:
                    items.append(
                        RenderItem(
                            kind="placeholder",
                            media_type=media,
                            text=f"[unrenderable artifact part: {media}]",
                        )
                    )
        return RenderPlan(items=tuple(items))

    @abstractmethod
    def render(self, plan: RenderPlan) -> None: ...


def _state_name(state: int) -> str:
    from a2a.types import TaskState

    return TaskState.Name(state).removeprefix("TASK_STATE_")


__all__ = [
    "TEXT_PLAIN",
    "ItemKind",
    "RenderItem",
    "RenderPlan",
    "Renderer",
    "part_media_type",
    "plan_message",
]
