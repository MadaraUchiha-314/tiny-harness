"""Abuse case 9: an action naming a surface or component the task did not create is discarded."""

from __future__ import annotations

from tiny_harness.interaction.a2ui import (
    BASIC_CATALOG_ID,
    Action,
    SurfaceRegistry,
    parse_server_message,
)


def test_unknown_a2ui_action_discarded() -> None:
    registry = SurfaceRegistry().apply(
        parse_server_message(
            {
                "version": "v0.9.1",
                "createSurface": {"surfaceId": "real", "catalogId": BASIC_CATALOG_ID},
            }
        )
    )
    registry = registry.apply(
        parse_server_message(
            {
                "version": "v0.9.1",
                "updateComponents": {
                    "surfaceId": "real",
                    "components": [{"id": "root", "component": "Text", "text": "hi"}],
                },
            }
        )
    )
    forged_surface = Action(name="pay", surfaceId="forged", sourceComponentId="root", timestamp="t")
    forged_component = Action(
        name="pay", surfaceId="real", sourceComponentId="pay-btn", timestamp="t"
    )
    genuine = Action(name="ack", surfaceId="real", sourceComponentId="root", timestamp="t")
    assert not registry.accepts(forged_surface)
    assert not registry.accepts(forged_component)
    assert registry.accepts(genuine)
