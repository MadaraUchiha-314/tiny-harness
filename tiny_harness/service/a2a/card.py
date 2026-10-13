"""The agent card (R14.2, R14.3): built from the agent's description so every extension
the harness declares reaches ``capabilities.extensions``. No security scheme is declared
(decision-003): the perimeter authenticates."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from a2a.types import AgentCapabilities, AgentCard, AgentExtension, AgentInterface, AgentSkill
from pydantic import BaseModel, ConfigDict

from tiny_harness.config import CardConfig
from tiny_harness.config import AgentConfig
from tiny_harness.errors import ConfigError
from tiny_harness.harness.agents import A2UI_EXT_URI, SUPPORTED_EXTENSIONS
from tiny_harness.harness.channels import CHANNEL_EXT_MEDIA_TYPE, CHANNEL_EXT_URI
from tiny_harness.harness.commands import COMMANDS_EXT_URI, CommandsExtensionParams, CommandSpec
from tiny_harness.harness.core import STATUS_EXT_URI, TASK_EXT_MEDIA_TYPE, TASK_EXT_URI
from tiny_harness.interaction.a2ui import BASIC_CATALOG_ID
from tiny_harness.service.inbox import EVENT_MEDIA_TYPE

A2UI_MEDIA_TYPE: Final = "application/a2ui+json"
PROTOCOL_VERSION: Final = "1.0"

EXTENSION_DESCRIPTIONS: Final[dict[str, str]] = {
    TASK_EXT_URI: "tiny-harness task extension: name, goal, acceptance criteria, participants, "
    "plan and sub-tasks in Task.metadata; event envelopes as data parts",
    CHANNEL_EXT_URI: "tiny-harness channels: messages, help requests and replies as data parts",
    A2UI_EXT_URI: "A2UI 0.9.1 surfaces and actions as application/a2ui+json parts",
    STATUS_EXT_URI: "tiny-harness status: why a task is INPUT_REQUIRED (sub_state) in "
    "Task.metadata and TaskStatusUpdateEvent.metadata",
    COMMANDS_EXT_URI: "tiny-harness slash commands: params.commands lists each /<name> "
    "with its description and argument hint",
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


def describe(card: CardConfig) -> AgentDescription:
    """The description ``[card]`` configures (issue-34 R5); an unset field keeps its default."""
    fields = card.model_dump(exclude_none=True, exclude={"skills"})
    skills = tuple(AgentSkillSpec.model_validate(s.model_dump()) for s in card.skills)
    return AgentDescription(**fields, skills=skills)


def normalize_prefix(prefix: str | None) -> str:
    """A mount prefix as ``/a/b``: a leading slash, no trailing slash; ``""`` for the root."""
    if prefix is None:
        return ""
    stripped = prefix.strip().strip("/")
    return f"/{stripped}" if stripped else ""


def public_url(base_url: str, prefix: str | None = None) -> str:
    """Where clients reach this agent, with no trailing slash (issue-36 R2.3, R2.4).

    ``base_url``'s own path is the prefix when it has one; a ``prefix`` argument is added to
    a ``base_url`` without a path, and must equal the path of one that has a path. A
    mismatch is a ``ConfigError`` naming both, so a card never carries a URL the agent
    is not served at."""
    split = urlsplit(base_url)
    base_path = normalize_prefix(split.path)
    wanted = normalize_prefix(prefix)
    if base_path and wanted and base_path != wanted:
        raise ConfigError(
            f"the mount prefix {wanted!r} disagrees with server.base_url's path {base_path!r}",
            variable="server.base_url",
        )
    path = base_path or wanted
    return urlunsplit((split.scheme, split.netloc, path, "", ""))


def describe_agent(config: AgentConfig, agent: AgentDescription | None = None) -> AgentDescription:
    """The card's description: ``agent`` when given in code, else the default, with
    ``[agent]``'s name and description over it when set (issue-36 R4.6)."""
    base = agent or AgentDescription()
    updates: dict[str, str] = {}
    if config.name is not None:
        updates["name"] = config.name
    if config.description is not None:
        updates["description"] = config.description
    return base.model_copy(update=updates) if updates else base


def build_agent_card(
    agent: AgentDescription, base_url: str, *, commands: Sequence[CommandSpec] = ()
) -> AgentCard:
    """The card; ``commands`` are the registered commands the commands extension lists
    (issue-25 R6.7)."""
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
        if uri == COMMANDS_EXT_URI:
            params = CommandsExtensionParams(commands=tuple(commands))
            extension.params.update(params.model_dump(mode="json"))
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
    "describe",
    "describe_agent",
    "normalize_prefix",
    "public_url",
]
