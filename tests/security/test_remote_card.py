"""Abuse case 5: a remote card the harness cannot honour is refused before anything is sent."""

from __future__ import annotations

import pytest
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    SecurityRequirement,
    SecurityScheme,
)

from tiny_harness.errors import UnsupportedExtensionError
from tiny_harness.harness.agents import SUPPORTED_EXTENSIONS, validate_card
from tiny_harness.harness.core import TASK_EXT_URI


def card(*extensions: AgentExtension) -> AgentCard:
    return AgentCard(name="remote", capabilities=AgentCapabilities(extensions=list(extensions)))


def test_remote_card_with_unknown_required_ext_refused() -> None:
    validate_card(card(AgentExtension(uri=TASK_EXT_URI, required=True)))
    validate_card(card(AgentExtension(uri="https://example.com/ext/optional/v1", required=False)))
    with pytest.raises(UnsupportedExtensionError) as info:
        validate_card(card(AgentExtension(uri="https://example.com/ext/evil/v1", required=True)))
    assert info.value.detail["extension"] == "https://example.com/ext/evil/v1"
    assert all(uri in SUPPORTED_EXTENSIONS for uri in (TASK_EXT_URI,))


def test_remote_card_with_security_scheme_refused() -> None:
    secured = card()
    secured.security_schemes["bearer"].CopyFrom(SecurityScheme())
    with pytest.raises(UnsupportedExtensionError):
        validate_card(secured)
    required = card()
    required.security_requirements.append(SecurityRequirement())
    with pytest.raises(UnsupportedExtensionError):
        validate_card(required)
