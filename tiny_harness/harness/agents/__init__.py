"""Agents, local and remote (R1.1, R7)."""

from tiny_harness.harness.agents.base import (
    A2UI_EXT_URI,
    SELF_AGENT_ID,
    SUPPORTED_EXTENSIONS,
    A2AEvent,
    Agent,
)
from tiny_harness.harness.agents.remote import RemoteAgent, unwrap, validate_card
from tiny_harness.harness.agents.roster import AgentRoster, build_roster

__all__ = [
    "A2UI_EXT_URI",
    "SELF_AGENT_ID",
    "SUPPORTED_EXTENSIONS",
    "A2AEvent",
    "Agent",
    "AgentRoster",
    "RemoteAgent",
    "build_roster",
    "unwrap",
    "validate_card",
]
