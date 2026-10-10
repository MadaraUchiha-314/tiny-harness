"""Surfaces (R20.1, R20.8): where a user meets the harness. Text is the only modality."""

from __future__ import annotations

from enum import StrEnum

from tiny_harness.harness.entities import Entity, EntityKind, EntityRef


class Modality(StrEnum):
    TEXT = "text"


class Surface(Entity):
    """A connected surface: its modality and the renderer it draws with."""

    kind = EntityKind.SURFACE

    def __init__(self, ref: EntityRef, *, modality: Modality, renderer: EntityRef) -> None:
        super().__init__(ref)
        self.modality = modality
        self.renderer = renderer


__all__ = ["Modality", "Surface"]
