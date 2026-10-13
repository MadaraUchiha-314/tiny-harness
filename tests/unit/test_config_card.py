"""This harness's own agent card from ``[card]`` (issue-34 R5): an absent section keeps
today's card; a set section names, describes and lists the skills of this agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiny_harness.config import CardConfig, Settings
from tiny_harness.errors import ConfigError
from tiny_harness.service.a2a.card import AgentDescription, build_agent_card, describe

ENV = {"OPENAI_API_KEY": "sk-secret"}

BASE = """
[temporal]
mode = "embedded"

[server]
base_url = "http://127.0.0.1:8080"

[store]
sqlite_path = "{store}"
{extra}
"""

LEDGER = """
[card]
name = "Order ledger"
description = "Answers order status questions from the order book."
version = "2.1.0"

[[card.skills]]
id = "lookup-order"
name = "Look up an order"
description = "Status, items and shipping of an order, by number."
tags = ["orders"]
examples = ["Where is order 48213?"]
"""


def load(tmp_path: Path, extra: str = "") -> Settings:
    path = tmp_path / "config.toml"
    path.write_text(BASE.format(store=tmp_path / "s.sqlite3", extra=extra))
    return Settings.load(path, env=ENV)


def test_without_a_card_section_the_card_is_the_default(tmp_path: Path) -> None:
    settings = load(tmp_path)
    assert settings.card == CardConfig()
    assert describe(settings.card) == AgentDescription()


def test_a_card_section_names_describes_and_lists_skills(tmp_path: Path) -> None:
    card = build_agent_card(describe(load(tmp_path, LEDGER).card), "http://127.0.0.1:8080")
    assert (card.name, card.version) == ("Order ledger", "2.1.0")
    assert card.description == "Answers order status questions from the order book."
    (skill,) = card.skills
    assert (skill.id, skill.name) == ("lookup-order", "Look up an order")
    assert skill.description == "Status, items and shipping of an order, by number."
    assert list(skill.tags) == ["orders"] and list(skill.examples) == ["Where is order 48213?"]


def test_an_unset_field_keeps_its_default(tmp_path: Path) -> None:
    settings = load(tmp_path, '[card]\ndescription = "Answers order questions."')
    described = describe(settings.card)
    assert described.description == "Answers order questions."
    assert (described.name, described.version) == (AgentDescription().name, "0.1.0")
    assert described.extensions == AgentDescription().extensions


@pytest.mark.parametrize(
    "extra",
    [
        '[card]\nname = ""',
        '[card]\ndescription = "  "',
        '[card]\nurl = "http://elsewhere"',
        '[[card.skills]]\nid = "a"\nname = "A"\n[[card.skills]]\nid = "a"\nname = "B"',
        '[[card.skills]]\nid = ""\nname = "A"',
    ],
    ids=["empty-name", "blank-description", "unknown-key", "duplicate-skill", "empty-skill-id"],
)
def test_an_invalid_card_section_is_refused_at_startup(tmp_path: Path, extra: str) -> None:
    with pytest.raises(ConfigError):
        load(tmp_path, extra)
