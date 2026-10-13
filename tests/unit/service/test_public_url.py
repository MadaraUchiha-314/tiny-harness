"""Where an agent is reached (issue-36 R2.3, R2.4, R4.6): ``public_url`` from ``base_url``
and the mount prefix, and the card's name and description from ``[agent]``."""

from __future__ import annotations

import pytest

from tiny_harness.config import AgentConfig
from tiny_harness.errors import ConfigError
from tiny_harness.service.a2a.card import (
    AgentDescription,
    build_agent_card,
    describe_agent,
    normalize_prefix,
    public_url,
)


@pytest.mark.parametrize(
    ("base", "prefix", "expected"),
    [
        ("http://h:8080", None, "http://h:8080"),
        ("http://h:8080/", None, "http://h:8080"),
        ("http://h:8080/", "/agents/a", "http://h:8080/agents/a"),
        ("http://h:8080", "agents/a/", "http://h:8080/agents/a"),
        ("http://h:8080/agents/a", None, "http://h:8080/agents/a"),
        ("http://h:8080/agents/a/", "/agents/a", "http://h:8080/agents/a"),
        ("http://h:8080/", "/", "http://h:8080"),
    ],
)
def test_public_url(base: str, prefix: str | None, expected: str) -> None:
    assert public_url(base, prefix) == expected


def test_a_prefix_that_disagrees_with_base_url_is_refused() -> None:
    with pytest.raises(ConfigError) as caught:
        public_url("http://h/agents/a", "/agents/b")
    assert "/agents/b" in caught.value.message and "/agents/a" in caught.value.message


@pytest.mark.parametrize(("raw", "normal"), [(None, ""), ("/", ""), ("a", "/a"), ("/a/b/", "/a/b")])
def test_normalize_prefix(raw: str | None, normal: str) -> None:
    assert normalize_prefix(raw) == normal


def test_the_card_carries_the_prefixed_url() -> None:
    card = build_agent_card(AgentDescription(), public_url("http://h:8090", "/agents/b"))
    assert {i.url for i in card.supported_interfaces} == {"http://h:8090/agents/b/"}


def test_the_agent_section_names_the_card() -> None:
    described = describe_agent(AgentConfig(id="billing", name="Billing", description="Bills."))
    assert (described.name, described.description) == ("Billing", "Bills.")
    assert describe_agent(AgentConfig()) == AgentDescription()
