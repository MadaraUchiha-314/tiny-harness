"""Renderers (R20.1, R20.4, R20.7): what a surface can draw, and the typed placeholder for
what it cannot. ``RenderPlan`` is the renderer-neutral description a TUI or a web page
turns into widgets; MCP Apps (``text/html;profile=mcp-app``) can be declared in
``supported`` later without changing the interface.

issue-38: a ``url`` file part of an accepted image or audio type, or of the spoken-reply
PCM type, is a ``media`` item (its URL, file name and part metadata) for a renderer that
lists the type in ``supported``. Nothing else is: no SVG, no HTML, no raw bytes."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Literal

from a2a.types import Message, Part, Task, TaskStatusUpdateEvent
from google.protobuf import json_format
from pydantic import BaseModel, ConfigDict

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef
from tiny_harness.harness.media import ACCEPTED, PCM_MEDIA_TYPE
from tiny_harness.jsontypes import JsonObject

TEXT_PLAIN = "text/plain"
type ItemKind = Literal["text", "status", "data", "placeholder", "media"]
type ItemRole = Literal["user", "agent", "system"]


class RenderItem(BaseModel):
    """One thing to draw: text, a status change, a data part a renderer knows, a medium
    (``url``, ``name`` and the part metadata in ``data``, issue-38), or the placeholder
    naming the kind it does not (R20.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ItemKind
    media_type: str = TEXT_PLAIN
    text: str = ""
    data: JsonObject | None = None
    role: ItemRole = "agent"
    url: str = ""
    name: str = ""


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


def is_media_part(part: Part) -> bool:
    """A ``url`` file part of an accepted media type or the spoken-reply type (issue-38)."""
    return part.HasField("url") and (
        part.media_type in ACCEPTED or part.media_type == PCM_MEDIA_TYPE
    )


def plan_part(
    part: Part, supported: frozenset[str], *, role: ItemRole = "agent", unrenderable: str
) -> RenderItem:
    """One part as an item; ``unrenderable`` names it in the placeholder."""
    media = part_media_type(part)
    if part.HasField("text") and TEXT_PLAIN in supported:
        return RenderItem(kind="text", text=part.text, role=role)
    if part.HasField("data") and media in supported:
        data = json_format.MessageToDict(part.data)
        return RenderItem(kind="data", media_type=media, data=data, role=role)
    if is_media_part(part) and media in supported:
        return RenderItem(
            kind="media",
            media_type=media,
            url=part.url,
            name=part.filename,
            data=json_format.MessageToDict(part.metadata),
            role=role,
        )
    return RenderItem(
        kind="placeholder", media_type=media, text=f"[{unrenderable}: {media}]", role=role
    )


def plan_message(message: Message, supported: frozenset[str]) -> list[RenderItem]:
    role: ItemRole = "user" if message.role == 1 else "agent"
    return [
        plan_part(part, supported, role=role, unrenderable="unrenderable part")
        for part in message.parts
    ]


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
            items.extend(
                plan_part(part, self.supported, unrenderable="unrenderable artifact part")
                for part in event.artifact.parts
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
    "ItemRole",
    "RenderItem",
    "RenderPlan",
    "Renderer",
    "is_media_part",
    "part_media_type",
    "plan_message",
    "plan_part",
]
