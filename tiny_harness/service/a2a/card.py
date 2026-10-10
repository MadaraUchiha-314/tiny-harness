"""The agent card (R14.2, R14.3): built from the agent's description so every extension
the harness declares reaches ``capabilities.extensions``. No security scheme is declared
(decision-003): the perimeter authenticates."""

from __future__ import annotations

from typing import Final

from a2a.types import AgentCapabilities, AgentCard, AgentExtension, AgentInterface, AgentSkill
from pydantic import BaseModel, ConfigDict

from tiny_harness.harness.agents import A2UI_EXT_URI, SUPPORTED_EXTENSIONS
from tiny_harness.harness.channels import CHANNEL_EXT_MEDIA_TYPE, CHANNEL_EXT_URI
from tiny_harness.harness.core import TASK_EXT_MEDIA_TYPE, TASK_EXT_URI
from tiny_harness.interaction.a2ui import BASIC_CATALOG_ID

A2UI_MEDIA_TYPE: Final = "application/a2ui+json"
EVENT_MEDIA_TYPE: Final = "application/vnd.tiny-harness.event+json"
PROTOCOL_VERSION: Final = "1.0"

EXTENSION_DESCRIPTIONS: Final[dict[str, str]] = {
    TASK_EXT_URI: "tiny-harness task extension: name, goal, acceptance criteria, participants, "
    "plan and sub-tasks in Task.metadata; event envelopes as data parts",
    CHANNEL_EXT_URI: "tiny-harness channels: messages, help requests and replies as data parts",
    A2UI_EXT_URI: "A2UI 0.9.1 surfaces and actions as application/a2ui+json parts",
}


class AgentDescription(BaseModel):
    """What the card is built from: the agent entity's identity and skills."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = "tiny-harness"
    description: str = "A tiny agent harness: tasks, plans, participants, tools and skills over A2A"
    version: str = "0.1.0"
    skills: tuple[AgentSkillSpec, ...] = ()
    extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS


class AgentSkillSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


def build_agent_card(agent: AgentDescription, base_url: str) -> AgentCard:
    url = base_url.rstrip("/") + "/"
    extensions: list[AgentExtension] = []
    for uri in agent.extensions:
        extension = AgentExtension(
            uri=uri, description=EXTENSION_DESCRIPTIONS.get(uri, ""), required=False
        )
        if uri == A2UI_EXT_URI:
            extension.params.update(
                {"supportedCatalogIds": [BASIC_CATALOG_ID], "acceptsInlineCatalogs": False}
            )
        extensions.append(extension)
    return AgentCard(
        name=agent.name,
        description=agent.description,
        version=agent.version,
        supported_interfaces=[
            AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version=PROTOCOL_VERSION),
            AgentInterface(
                url=url, protocol_binding="HTTP+JSON", protocol_version=PROTOCOL_VERSION
            ),
        ],
        capabilities=AgentCapabilities(
            streaming=True, push_notifications=True, extensions=extensions
        ),
        default_input_modes=[
            "text/plain",
            TASK_EXT_MEDIA_TYPE,
            CHANNEL_EXT_MEDIA_TYPE,
            EVENT_MEDIA_TYPE,
            A2UI_MEDIA_TYPE,
        ],
        default_output_modes=[
            "text/plain",
            TASK_EXT_MEDIA_TYPE,
            CHANNEL_EXT_MEDIA_TYPE,
            A2UI_MEDIA_TYPE,
        ],
        skills=[
            AgentSkill(
                id=s.id,
                name=s.name,
                description=s.description,
                tags=list(s.tags),
                examples=list(s.examples),
            )
            for s in agent.skills
        ],
    )


__all__ = [
    "A2UI_EXT_URI",
    "A2UI_MEDIA_TYPE",
    "EVENT_MEDIA_TYPE",
    "EXTENSION_DESCRIPTIONS",
    "PROTOCOL_VERSION",
    "SUPPORTED_EXTENSIONS",
    "AgentDescription",
    "AgentSkillSpec",
    "build_agent_card",
]
