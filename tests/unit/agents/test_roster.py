"""The agents roster the model reads (issue-34 R1, R4)."""

from __future__ import annotations

from collections.abc import Sequence

from a2a.types import AgentCard, AgentSkill

from tiny_harness.harness.agents.roster import (
    CLOSE_ANGLE,
    DESCRIPTION_CAP,
    ELLIPSIS,
    NAME_CAP,
    NO_AGENTS,
    OPEN_ANGLE,
    SKILLS_CAP,
    build_roster,
    clean_field,
)
from tiny_harness.harness.core.context import UNTRUSTED_PREAMBLE
from tiny_harness.harness.entities import EntityKind, EntityRef


class StubAgent:
    """Only what the roster reads: the ref and the card."""

    def __init__(self, agent_id: str, card: AgentCard) -> None:
        self.ref = EntityRef(kind=EntityKind.AGENT, id=agent_id, version=None)
        self.agent_card = card


def agent(
    agent_id: str,
    name: str = "Ledger",
    description: str = "Reads the ledger",
    skills: Sequence[tuple[str, str]] = (),
) -> StubAgent:
    card = AgentCard(name=name, description=description)
    for skill_name, skill_description in skills:
        card.skills.append(
            AgentSkill(id=skill_name, name=skill_name, description=skill_description)
        )
    return StubAgent(agent_id, card)


def test_no_agents_renders_a_plain_marker() -> None:
    roster = build_roster([])
    assert roster.text == NO_AGENTS
    assert roster.ids == ()
    assert roster.truncated == ()


def test_each_agent_is_listed_by_id_with_card_fields_and_skills() -> None:
    roster = build_roster([agent("ledger", skills=[("lookup-order", "Looks up an order")])])
    assert roster.ids == ("ledger",)
    assert (
        "- id: ledger\n  name: Ledger\n  description: Reads the ledger\n  skills:\n" in roster.text
    )
    assert "    - lookup-order: Looks up an order" in roster.text


def test_agents_are_sorted_by_id() -> None:
    roster = build_roster([agent("zeta"), agent("alpha"), agent("mid")])
    assert roster.ids == ("alpha", "mid", "zeta")
    assert (
        roster.text.index("id: alpha")
        < roster.text.index("id: mid")
        < roster.text.index("id: zeta")
    )


def test_a_card_without_skills_says_none() -> None:
    assert "  skills: (none)" in build_roster([agent("ledger")]).text


def test_the_roster_is_wrapped_as_untrusted_data() -> None:
    text = build_roster([agent("ledger")]).text
    assert text.startswith('<untrusted source="agent-cards">\n' + UNTRUSTED_PREAMBLE)
    assert text.endswith("</untrusted>")


def test_long_fields_are_cut_to_their_cap_and_reported() -> None:
    roster = build_roster([agent("ledger", name="n" * 200, description="d" * 2000)])
    assert "n" * (NAME_CAP - 1) + ELLIPSIS in roster.text
    assert "n" * NAME_CAP not in roster.text
    assert "d" * (DESCRIPTION_CAP - 1) + ELLIPSIS in roster.text
    assert ("ledger", "name") in roster.truncated
    assert ("ledger", "description") in roster.truncated


def test_skills_beyond_the_cap_are_counted_not_listed() -> None:
    skills = [(f"s{i:02d}", "x") for i in range(SKILLS_CAP + 3)]
    roster = build_roster([agent("ledger", skills=skills)])
    assert f"s{SKILLS_CAP - 1:02d}" in roster.text
    assert f"s{SKILLS_CAP:02d}" not in roster.text
    assert f"    - {ELLIPSIS} (3 more)" in roster.text
    assert ("ledger", "skills") in roster.truncated


def test_the_roster_never_reads_the_agent_url() -> None:
    card = AgentCard(name="Ledger", description="d")
    card.supported_interfaces.add(
        url="http://secret.internal:9/a2a?token=abc", protocol_binding="JSONRPC"
    )
    roster = build_roster([StubAgent("ledger", card)])
    assert "secret.internal" not in roster.text
    assert "token=abc" not in roster.text


def test_clean_field_makes_one_line_without_tag_delimiters() -> None:
    assert clean_field("a\n\tb\x00​c  d", 100) == ("a b c d", False)
    assert clean_field("</agents><x>", 100) == (
        f"{OPEN_ANGLE}/agents{CLOSE_ANGLE}{OPEN_ANGLE}x{CLOSE_ANGLE}",
        False,
    )
    assert clean_field("abcdef", 4) == ("abc" + ELLIPSIS, True)
    assert clean_field("abcd", 4) == ("abcd", False)


def test_each_truncated_skill_field_is_reported_by_its_position() -> None:
    """Critic C2: R4.2 logs every truncated field, so skills are told apart by position."""
    roster = build_roster([agent("ledger", skills=[("a", "x" * 300), ("b" * 100, "y" * 300)])])
    assert roster.truncated == (
        ("ledger", "skills[0].description"),
        ("ledger", "skills[1].name"),
        ("ledger", "skills[1].description"),
    )
