"""Agent Plugins 1.0.0 manifest models and the tiny-harness namespace (R3.1-R3.3).

A plugin is a directory with ``plugin.json``, optional ``skills/<name>/SKILL.md``
directories and an optional ``mcp.json``. Hooks and prompts are outside the
specification's v1 format, so this harness reads them from the plugin's client-specific
directory ``io.github.madarauchiha-314.tiny-harness/`` (``hooks.json``, ``prompts/*.md``,
``systemprompt.md``) and ignores other clients' namespaced directories. ``Plugin`` is
also the programmatic form: build it in code and hand it to the loader (R3.2).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

NAMESPACE = "io.github.madarauchiha-314.tiny-harness"
"""The reverse-domain namespace this harness owns in a plugin (spec § 8)."""

PLUGIN_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
PLUGIN_ROOT_VAR = "PLUGIN_ROOT"
PLUGIN_DATA_VAR = "PLUGIN_DATA"

PluginName = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=64, pattern=r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$"
    ),
]


class Author(BaseModel, extra="forbid"):
    name: str | None = None
    email: str | None = None
    url: str | None = None


class PluginManifest(BaseModel, extra="forbid"):
    """``plugin.json``. Unknown top-level keys are stripped (and reported) before
    validation, as the specification makes them non-fatal; everything else is strict."""

    schema_id: str = Field(alias="$schema")
    name: PluginName
    version: str | None = None
    description: str | None = None
    author: Author | None = None
    homepage: str | None = None
    repository: str | None = None
    license: str | None = None
    keywords: tuple[str, ...] = ()
    extensions: Mapping[str, Mapping[str, object]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", populate_by_name=True, regex_engine="python-re")


class McpStdioServer(BaseModel, extra="forbid"):
    type: Literal["stdio"]
    command: str = Field(min_length=1)
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class McpHttpServer(BaseModel, extra="forbid"):
    type: Literal["streamable-http"]
    url: HttpUrl
    headers: Mapping[str, str] = Field(default_factory=dict)


class McpSseServer(BaseModel, extra="forbid"):
    """Legacy HTTP+SSE; the harness does not support it and skips the entry with a reason."""

    type: Literal["sse"]
    url: HttpUrl
    headers: Mapping[str, str] = Field(default_factory=dict)


McpServer = Annotated[McpStdioServer | McpHttpServer | McpSseServer, Field(discriminator="type")]


class McpConfig(BaseModel, extra="forbid"):
    """``mcp.json``: the required ``$schema`` and ``mcpServers`` and nothing else."""

    schema_id: str = Field(alias="$schema")
    mcp_servers: Mapping[str, McpServer] = Field(alias="mcpServers")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class HookDef(BaseModel, extra="forbid"):
    """One entry of the namespace directory's ``hooks.json``: exactly one transport."""

    name: str = Field(min_length=1)
    priority: int = 500
    points: tuple[str, ...] | None = None
    import_path: str | None = None
    url: HttpUrl | None = None
    mcp: McpStdioServer | McpHttpServer | None = None

    @model_validator(mode="after")
    def _exactly_one_transport(self) -> Self:
        if sum(x is not None for x in (self.import_path, self.url, self.mcp)) != 1:
            raise ValueError("a hook needs exactly one of import_path, url or mcp")
        return self


class HooksFile(BaseModel, extra="forbid"):
    hooks: tuple[HookDef, ...] = ()


class ComponentKind(StrEnum):
    SKILL = "skill"
    MCP_SERVER = "mcp_server"
    HOOK = "hook"
    PROMPT = "prompt"
    SYSTEM_PROMPT = "system_prompt"


class Plugin(BaseModel):
    """A validated plugin, from a directory or built in code (the programmatic form).

    Paths are absolute. With a ``root``, every path is required to be inside it
    (R3.6); without one (programmatic), the caller vouches for them.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    manifest: PluginManifest
    root: Path | None = None
    skills: tuple[Path, ...] = ()
    mcp: Mapping[str, McpStdioServer | McpHttpServer | McpSseServer] = Field(default_factory=dict)
    hooks: tuple[HookDef, ...] = ()
    prompts: tuple[Path, ...] = ()
    systemprompt: Path | None = None
    notes: tuple[str, ...] = ()


class LoadedComponent(BaseModel, frozen=True):
    kind: ComponentKind
    id: str


class SkippedComponent(BaseModel, frozen=True):
    kind: ComponentKind
    id: str
    code: str
    reason: str


class LoadReport(BaseModel, frozen=True):
    """What one plugin load did: every component loaded or skipped with its reason (R3.5)."""

    plugin: str
    loaded: tuple[LoadedComponent, ...] = ()
    skipped: tuple[SkippedComponent, ...] = ()
    notes: tuple[str, ...] = ()

    def loaded_ids(self, kind: ComponentKind) -> tuple[str, ...]:
        return tuple(c.id for c in self.loaded if c.kind is kind)


__all__ = [
    "MCP_SCHEMA_ID",
    "NAMESPACE",
    "PLUGIN_DATA_VAR",
    "PLUGIN_ROOT_VAR",
    "PLUGIN_SCHEMA_ID",
    "Author",
    "ComponentKind",
    "HookDef",
    "HooksFile",
    "LoadReport",
    "LoadedComponent",
    "McpConfig",
    "McpHttpServer",
    "McpServer",
    "McpSseServer",
    "McpStdioServer",
    "Plugin",
    "PluginManifest",
    "PluginName",
    "SkippedComponent",
]
