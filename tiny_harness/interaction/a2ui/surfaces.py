"""The surfaces a task created and the components on them (abuse case 9): an action
naming a surface or component the task did not create is discarded."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from tiny_harness.interaction.a2ui.messages import (
    Action,
    CreateSurface,
    DeleteSurface,
    ServerMessage,
    UpdateComponents,
)


class SurfaceRegistry(BaseModel):
    """Immutable: ``apply`` returns the registry after a server message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    surfaces: Mapping[str, tuple[str, ...]] = Field(default_factory=dict)

    def apply(self, message: ServerMessage) -> SurfaceRegistry:
        surfaces = dict(self.surfaces)
        if isinstance(message, CreateSurface):
            surfaces.setdefault(message.surface_id, ())
        elif isinstance(message, UpdateComponents):
            known = surfaces.get(message.surface_id, ())
            surfaces[message.surface_id] = tuple(dict.fromkeys((*known, *message.component_ids())))
        elif isinstance(message, DeleteSurface):
            surfaces.pop(message.surface_id, None)
        return SurfaceRegistry(surfaces=surfaces)

    def accepts(self, action: Action) -> bool:
        components = self.surfaces.get(action.surface_id)
        return components is not None and action.source_component_id in components


__all__ = ["SurfaceRegistry"]
