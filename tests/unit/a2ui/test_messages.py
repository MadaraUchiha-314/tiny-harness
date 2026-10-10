"""A2UI 0.9.1 payloads (R20.5): valid ones parse, invalid ones are refused with a path."""

from __future__ import annotations

import pytest

from tiny_harness.interaction.a2ui import (
    A2UI_VERSION,
    BASIC_CATALOG_ID,
    A2UIValidationError,
    Action,
    CreateSurface,
    SurfaceRegistry,
    UpdateComponents,
    parse_client_message,
    parse_server_message,
)
from tiny_harness.jsontypes import JsonObject

CARD: JsonObject = {
    "version": "v0.9.1",
    "updateComponents": {
        "surfaceId": "s1",
        "components": [
            {"id": "root", "component": "Card", "child": "col"},
            {"id": "col", "component": "Column", "children": ["title", "pick", "ok"]},
            {"id": "title", "component": "Text", "text": "Proposed resolution"},
            {
                "id": "pick",
                "component": "ChoicePicker",
                "label": "Resolution",
                "options": [
                    {"label": "Ship replacement now", "value": "replace"},
                    {"label": "Refund after photo", "value": "refund"},
                ],
                "value": {"path": "/resolution"},
            },
            {
                "id": "ok",
                "component": "Button",
                "child": "ok-label",
                "action": {
                    "event": {"name": "confirm", "context": {"choice": {"path": "/resolution"}}}
                },
            },
            {"id": "ok-label", "component": "Text", "text": "Confirm"},
        ],
    },
}


def test_server_messages_parse_and_round_trip() -> None:
    create = parse_server_message(
        {
            "version": A2UI_VERSION,
            "createSurface": {"surfaceId": "s1", "catalogId": BASIC_CATALOG_ID},
        }
    )
    assert isinstance(create, CreateSurface) and create.surface_id == "s1"
    assert create.payload()["createSurface"] == {"surfaceId": "s1", "catalogId": BASIC_CATALOG_ID}
    update = parse_server_message(CARD)
    assert isinstance(update, UpdateComponents)
    assert update.component_ids() == ("root", "col", "title", "pick", "ok", "ok-label")
    assert parse_server_message(update.payload()) == update
    delete = parse_server_message({"version": "v0.9", "deleteSurface": {"surfaceId": "s1"}})
    assert delete.kind == "deleteSurface"


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"version": "v0.9.1", "createSurface": {"catalogId": "x"}}, "surfaceId"),
        ({"version": "v2", "deleteSurface": {"surfaceId": "s1"}}, "version"),
        (
            {
                "version": "v0.9.1",
                "updateComponents": {
                    "surfaceId": "s1",
                    "components": [{"id": "root", "component": "Hologram"}],
                },
            },
            "components",
        ),
        ({"version": "v0.9.1", "bogus": {}}, ""),
    ],
)
def test_invalid_server_messages_are_refused(payload: JsonObject, fragment: str) -> None:
    with pytest.raises(A2UIValidationError) as info:
        parse_server_message(payload)
    assert info.value.code == "a2ui.invalid"
    assert fragment in info.value.detail.get("path", "") + info.value.detail.get("error", "")


def test_client_action_parses_and_errors_are_typed() -> None:
    action = parse_client_message(
        {
            "version": "v0.9.1",
            "action": {
                "name": "confirm",
                "surfaceId": "s1",
                "sourceComponentId": "ok",
                "timestamp": "2026-10-09T12:00:00Z",
                "context": {"choice": "replace"},
            },
        }
    )
    assert isinstance(action, Action) and action.context == {"choice": "replace"}
    error = parse_client_message(
        {"version": "v0.9.1", "error": {"code": "RENDER_FAILED", "surfaceId": "s1", "message": "x"}}
    )
    assert error.kind == "error"
    with pytest.raises(A2UIValidationError):
        parse_client_message({"version": "v0.9.1", "action": {"name": "confirm"}})


def test_surface_registry_tracks_what_the_task_created() -> None:
    registry = SurfaceRegistry()
    registry = registry.apply(
        parse_server_message(
            {
                "version": A2UI_VERSION,
                "createSurface": {"surfaceId": "s1", "catalogId": BASIC_CATALOG_ID},
            }
        )
    )
    registry = registry.apply(parse_server_message(CARD))
    assert registry.surfaces == {"s1": ("root", "col", "title", "pick", "ok", "ok-label")}
    ok = Action(name="confirm", surfaceId="s1", sourceComponentId="ok", timestamp="t")
    assert registry.accepts(ok)
    assert not registry.accepts(ok.model_copy(update={"surface_id": "s2"}))
    gone = registry.apply(
        parse_server_message({"version": "v0.9.1", "deleteSurface": {"surfaceId": "s1"}})
    )
    assert not gone.accepts(ok)
