"""The agents roster: what the model reads about the agents it can delegate to (issue-34).

Built once at startup from the cards already fetched, so the static prefix it lands in
stays byte-identical across turns (R1.5). Card text is written by the remote side, so
every field is flattened to one line, stripped of tag delimiters and capped, and the body
sits inside the untrusted block (abuse cases 1-3). Only the id, the card's name and
description and its skills are read: never a URL or a security declaration (R1.3).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Protocol

from a2a.types import AgentCard
from pydantic import BaseModel

from tiny_harness.harness.core.context import NO_AGENTS, render_untrusted_text
from tiny_harness.harness.entities import EntityRef

NAME_CAP = 80
DESCRIPTION_CAP = 500
SKILL_DESCRIPTION_CAP = 200
SKILLS_CAP = 10
ELLIPSIS = "…"
OPEN_ANGLE = "\u2039"  # replaces "<": a field can never open or close a tag
CLOSE_ANGLE = "\u203a"  # replaces ">"
SOURCE = "agent-cards"

_SPACES = re.compile(r"\s+")


class CardHolder(Protocol):
    """What the roster reads of an agent."""

    @property
    def ref(self) -> EntityRef: ...

    @property
    def agent_card(self) -> AgentCard: ...


class AgentRoster(BaseModel, frozen=True):
    text: str
    ids: tuple[str, ...]
    truncated: tuple[tuple[str, str], ...]  # (agent id, field) per truncation


def clean_field(value: str, cap: int | None) -> tuple[str, bool]:
    """One line, no control characters, no tag delimiters, at most ``cap`` characters."""
    chars = (" " if unicodedata.category(c).startswith("C") else c for c in value)
    text = _SPACES.sub(" ", "".join(chars)).strip()
    text = text.replace("<", OPEN_ANGLE).replace(">", CLOSE_ANGLE)
    if cap is not None and len(text) > cap:
        return text[: cap - 1] + ELLIPSIS, True
    return text, False


def build_roster(agents: Sequence[CardHolder]) -> AgentRoster:
    """The ``agents`` section body: one entry per agent, sorted by id (R1.2, R1.5, R4.1)."""
    if not agents:
        return AgentRoster(text=NO_AGENTS, ids=(), truncated=())
    lines: list[str] = []
    truncated: list[tuple[str, str]] = []
    ordered = sorted(agents, key=lambda a: a.ref.id)

    def field(agent_id: str, name: str, value: str, cap: int | None) -> str:
        text, cut = clean_field(value, cap)
        if cut:
            truncated.append((agent_id, name))
        return text

    for agent in ordered:
        agent_id = agent.ref.id
        card = agent.agent_card
        lines.append(f"- id: {field(agent_id, 'id', agent_id, None)}")
        lines.append(f"  name: {field(agent_id, 'name', card.name, NAME_CAP)}")
        lines.append(
            f"  description: {field(agent_id, 'description', card.description, DESCRIPTION_CAP)}"
        )
        skills = list(card.skills)
        if not skills:
            lines.append("  skills: (none)")
            continue
        lines.append("  skills:")
        for skill in skills[:SKILLS_CAP]:
            name = field(agent_id, "skill name", skill.name, NAME_CAP)
            about = field(agent_id, "skill description", skill.description, SKILL_DESCRIPTION_CAP)
            lines.append(f"    - {name}: {about}")
        if len(skills) > SKILLS_CAP:
            lines.append(f"    - {ELLIPSIS} ({len(skills) - SKILLS_CAP} more)")
            truncated.append((agent_id, "skills"))
    return AgentRoster(
        text=render_untrusted_text("\n".join(lines), SOURCE),
        ids=tuple(a.ref.id for a in ordered),
        truncated=tuple(dict.fromkeys(truncated)),
    )


__all__ = [
    "CLOSE_ANGLE",
    "DESCRIPTION_CAP",
    "ELLIPSIS",
    "NAME_CAP",
    "NO_AGENTS",
    "OPEN_ANGLE",
    "SKILLS_CAP",
    "SKILL_DESCRIPTION_CAP",
    "AgentRoster",
    "CardHolder",
    "build_roster",
    "clean_field",
]
