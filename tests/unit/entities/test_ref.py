"""Entity references, kinds and remote locations (R1.1, R1.2, R1.4, R1.5)."""

import pytest
from pydantic import HttpUrl, ValidationError

from tiny_harness.harness.entities import (
    Entity,
    EntityKind,
    EntityRef,
    RemoteLocation,
    TransportProtocol,
)


def test_ref_version_is_optional_for_unversioned_kinds() -> None:
    ref = EntityRef(kind=EntityKind.CHANNEL, id="task-channel")
    assert ref.version is None
    assert ref.key == "channel:task-channel"


def test_ref_is_frozen_and_hashable() -> None:
    ref = EntityRef(kind=EntityKind.TOOL, id="orders.get_order", version="1.2.0")
    with pytest.raises(ValidationError):
        ref.id = "other"  # type: ignore[misc]
    assert {ref: 1}[EntityRef(kind=EntityKind.TOOL, id="orders.get_order", version="1.2.0")] == 1


def test_remote_location_requires_a_protocol() -> None:
    loc = RemoteLocation(
        url=HttpUrl("https://agents.example.com/billing"), protocol=TransportProtocol.A2A
    )
    assert loc.protocol is TransportProtocol.A2A
    with pytest.raises(ValidationError):
        RemoteLocation.model_validate({"url": "https://agents.example.com/billing"})


def test_every_entity_kind_is_a_known_construct() -> None:
    assert {k.value for k in EntityKind} == {
        "prompt",
        "skill",
        "tool",
        "llm",
        "system_one",
        "hook",
        "channel",
        "renderer",
        "surface",
        "store",
        "agent",
    }


class _Prompt(Entity):
    kind = EntityKind.PROMPT


def test_entity_subclass_declares_its_kind_and_ref() -> None:
    entity = _Prompt(ref=EntityRef(kind=EntityKind.PROMPT, id="default", version="1.0.0"))
    assert entity.kind is EntityKind.PROMPT
    assert entity.ref.id == "default"
    with pytest.raises(ValueError, match="kind"):
        _Prompt(ref=EntityRef(kind=EntityKind.TOOL, id="x"))
