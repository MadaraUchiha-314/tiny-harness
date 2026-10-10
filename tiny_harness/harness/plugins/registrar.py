"""The registrar that puts a plugin's components into the registry (R3.4).

Skills become ``Skill`` entities, prompts ``PromptEntity`` entities, a ``systemprompt.md``
replaces the system prompt, and MCP server definitions are collected for the tool
source (Layer 3) to connect. The plugin's manifest version is the entity version.
"""

from __future__ import annotations

from pathlib import Path

from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.plugins.models import McpHttpServer, McpStdioServer, Plugin
from tiny_harness.harness.prompts import SYSTEM_PROMPT_ID, PromptEntity
from tiny_harness.harness.skills import SkillLoader


class McpServerCatalog:
    """The MCP servers plugins declared, keyed by ``<plugin>/<server>``."""

    def __init__(self) -> None:
        self.servers: dict[str, tuple[Plugin, McpStdioServer | McpHttpServer]] = {}

    def add(self, plugin: Plugin, name: str, server: McpStdioServer | McpHttpServer) -> str:
        key = f"{plugin.manifest.name}/{name}"
        self.servers[key] = (plugin, server)
        return key


class RegistryRegistrar:
    """Registers skills, prompts and the system prompt in the registry; records MCP servers."""

    def __init__(self, registry: Registry, *, catalog: McpServerCatalog | None = None) -> None:
        self._registry = registry
        self.catalog = catalog or McpServerCatalog()
        self._skills = SkillLoader()
        self.override = False

    async def register_skill(self, plugin: Plugin, path: Path) -> str:
        skill = self._skills.load(path, version=plugin.manifest.version)
        await self._registry.add(
            RegistryEntry(ref=skill.ref, instance=skill), override=self.override
        )
        return skill.ref.id

    async def register_mcp_server(
        self, plugin: Plugin, name: str, server: McpStdioServer | McpHttpServer
    ) -> str:
        return self.catalog.add(plugin, name, server)

    async def register_prompt(self, plugin: Plugin, path: Path) -> str:
        prompt = PromptEntity.from_file(path, version=plugin.manifest.version)
        await self._registry.add(
            RegistryEntry(ref=prompt.ref, instance=prompt), override=self.override
        )
        return prompt.ref.id

    async def register_system_prompt(self, plugin: Plugin, path: Path) -> str:
        prompt = PromptEntity.from_file(path, id=SYSTEM_PROMPT_ID, version=None)
        ref = EntityRef(kind=EntityKind.PROMPT, id=SYSTEM_PROMPT_ID)
        await self._registry.add(RegistryEntry(ref=ref, instance=prompt), override=self.override)
        return SYSTEM_PROMPT_ID


__all__ = ["McpServerCatalog", "RegistryRegistrar"]
