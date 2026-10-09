"""Entity base, kinds, references and remote locations (R1.1, R1.2, R1.4, R1.5).

An *entity* is any pluggable core construct. Every instance is addressed by an
``EntityRef`` ``(kind, id, version)``; ``version`` is ``None`` for kinds that are not
versioned. A remote entity is reached through an application protocol, declared with
its URL, never implied.
"""

from __future__ import annotations

from abc import ABC
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, HttpUrl


class EntityKind(StrEnum):
    """The kinds of entity the harness knows; one abstract interface per kind (R1.1)."""

    PROMPT = "prompt"
    SKILL = "skill"
    TOOL = "tool"
    LLM = "llm"
    SYSTEM_ONE = "system_one"
    HOOK = "hook"
    CHANNEL = "channel"
    RENDERER = "renderer"
    STORE = "store"
    AGENT = "agent"


class EntityRef(BaseModel, frozen=True):
    """Registry reference. ``version`` is a PEP 440 specifier, ``"*"`` for the latest
    concrete version, or ``None`` when versioning does not apply to the kind (R1.2)."""

    kind: EntityKind
    id: str
    version: str | None = None

    @property
    def key(self) -> str:
        """``kind:id`` without the version, the registry's bucket key."""
        return f"{self.kind.value}:{self.id}"


class TransportProtocol(StrEnum):
    """The application protocol a remote entity speaks (R1.5)."""

    A2A = "a2a"
    MCP = "mcp"
    HTTPS = "https"


class RemoteLocation(BaseModel, frozen=True):
    """Where a remote entity lives. The protocol is required, so a remote entry can never
    lack one (R1.5)."""

    url: HttpUrl
    protocol: TransportProtocol


class Entity(ABC):
    """Base of every entity: a declared ``kind`` and the ``ref`` it is registered under.

    Subclasses set the class attribute ``kind``; constructing an entity with a ref of
    another kind is a programming error and raises ``ValueError``.
    """

    kind: ClassVar[EntityKind]

    def __init__(self, ref: EntityRef) -> None:
        if ref.kind is not self.kind:
            raise ValueError(
                f"ref kind {ref.kind.value!r} does not match entity kind {self.kind.value!r}"
            )
        self.ref = ref


__all__ = ["Entity", "EntityKind", "EntityRef", "RemoteLocation", "TransportProtocol"]
