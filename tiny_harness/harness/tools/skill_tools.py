"""The skill intrinsics (R5.3, R5.6): progressive disclosure as tool calls.

``list_skills`` returns names and descriptions; ``load_skill`` reads the skill, connects
the MCP servers an optional ``mcp.json`` inside the skill directory declares (the same
Agent Plugins format, a tiny-harness convention since Agent Skills declares no servers),
registers their tools, and returns a ``skill_loaded`` command carrying the body and the
tool definitions so the workflow records them in the agent state; ``unload_skill``
reverses it; ``list_skill_resources`` and ``load_skill_resource`` expose level three.
These run in the ``invoke_tool`` activity like every tool, so a different worker
reproduces the same context from the recorded command (R19.2).
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from tiny_harness.errors import EntityNotFoundError, SkillError, VersionNotFoundError
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.plugins import McpStdioServer, parse_mcp, prepare_stdio
from tiny_harness.harness.skills import Skill, skills_index
from tiny_harness.harness.tools.intrinsics import (
    ARGUMENTS,
    IntrinsicName,
    ListSkillResourcesArgs,
    LoadSkillArgs,
    LoadSkillResourceArgs,
    UnloadSkillArgs,
    definition,
)
from tiny_harness.harness.tools.mcp import McpToolSource, ServerSpec
from tiny_harness.harness.tools.models import Tool, ToolCall, ToolResult, WorkflowCommand
from tiny_harness.jsontypes import JsonValue


class LoadedSkill:
    def __init__(
        self, skill: Skill, tools: tuple[str, ...], sources: tuple[McpToolSource, ...]
    ) -> None:
        self.skill = skill
        self.tools = tools
        self.sources = sources


class SkillSession:
    """The worker-local record of which skills are loaded and which tools they brought."""

    def __init__(self, registry: Registry, *, data_root: Path) -> None:
        self._registry = registry
        self._data_root = data_root
        self.loaded: dict[str, LoadedSkill] = {}

    async def skills(self) -> list[Skill]:
        found: list[Skill] = []
        for ref in self._registry.list(EntityKind.SKILL):
            found.append(await self._registry.get(ref, Skill))
        return sorted(found, key=lambda s: s.name)

    async def skill(self, name: str) -> Skill:
        try:
            return await self._registry.get(
                EntityRef(kind=EntityKind.SKILL, id=name, version="*"), Skill
            )
        except (EntityNotFoundError, VersionNotFoundError) as exc:
            raise SkillError("no such skill", skill=name) from exc

    async def load(self, name: str) -> LoadedSkill:
        if name in self.loaded:
            return self.loaded[name]
        skill = await self.skill(name)
        sources: list[McpToolSource] = []
        tool_names: list[str] = []
        mcp_path = skill.root / "mcp.json"
        if mcp_path.is_file():
            config = parse_mcp(mcp_path)
            for server_name, server in config.mcp_servers.items():
                spec: ServerSpec
                if isinstance(server, McpStdioServer):
                    spec = prepare_stdio(server, root=skill.root, data=self._data_root / name)
                elif server.type == "streamable-http":
                    spec = str(server.url)
                else:
                    continue  # legacy SSE is not supported; skipped like the plugin loader does
                source = McpToolSource(f"{name}.{server_name}", spec, version=skill.ref.version)
                for tool in await source.tools():
                    await self._registry.add(
                        RegistryEntry(ref=tool.ref, instance=tool), override=True
                    )
                    tool_names.append(tool.definition.name)
                sources.append(source)
        loaded = LoadedSkill(skill, tuple(tool_names), tuple(sources))
        self.loaded[name] = loaded
        return loaded

    async def unload(self, name: str) -> LoadedSkill:
        loaded = self.loaded.pop(name, None)
        if loaded is None:
            raise SkillError("skill is not loaded", skill=name)
        for tool_name in loaded.tools:
            with contextlib.suppress(EntityNotFoundError):
                await self._registry.remove(
                    EntityRef(kind=EntityKind.TOOL, id=tool_name, version=loaded.skill.ref.version)
                )
        return loaded


class _SkillTool(Tool):
    def __init__(self, name: IntrinsicName, session: SkillSession) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.TOOL, id=name.value, version=None), definition(name)
        )
        self._name = name
        self._session = session

    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand:
        try:
            args = ARGUMENTS[self._name].model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult.error(call.call_id, "tool.invalid_arguments", str(exc))
        try:
            return await self._run(call, args)
        except SkillError as exc:
            return ToolResult.error(call.call_id, exc.code, exc.message)

    async def _run(self, call: ToolCall, args: object) -> ToolResult | WorkflowCommand:
        session = self._session
        if self._name is IntrinsicName.LIST_SKILLS:
            return ToolResult.text(
                call.call_id, skills_index(await session.skills()) or "(no skills)"
            )
        if self._name is IntrinsicName.LOAD_SKILL:
            loaded = await session.load(cast(LoadSkillArgs, args).name)
            payload: dict[str, JsonValue] = {
                "name": loaded.skill.name,
                "body": loaded.skill.body,
                "tools": list(loaded.tools),
            }
            return WorkflowCommand(
                kind="skill_loaded",
                call_id=call.call_id,
                payload=payload,
                result=ToolResult.text(call.call_id, loaded.skill.body),
            )
        if self._name is IntrinsicName.UNLOAD_SKILL:
            unloaded = await session.unload(cast(UnloadSkillArgs, args).name)
            return WorkflowCommand(
                kind="skill_unloaded",
                call_id=call.call_id,
                payload={"name": unloaded.skill.name, "tools": list(unloaded.tools)},
                result=ToolResult.text(call.call_id, f"unloaded {unloaded.skill.name}"),
            )
        if self._name is IntrinsicName.LIST_SKILL_RESOURCES:
            skill = await session.skill(cast(ListSkillResourcesArgs, args).name)
            lines = [f"- {r.kind}/{r.name}" for r in skill.resources()]
            return ToolResult.text(call.call_id, "\n".join(lines) or "(no resources)")
        resource_args = cast(LoadSkillResourceArgs, args)
        skill = await session.skill(resource_args.name)
        resource = skill.resource(resource_args.kind, resource_args.resource)
        try:
            text = resource.path.read_text()
        except UnicodeDecodeError:
            return ToolResult.error(call.call_id, "skill.invalid", "resource is not text")
        return ToolResult.text(call.call_id, text)


def skill_tools(session: SkillSession) -> tuple[Tool, ...]:
    """The five skill intrinsics bound to one session."""
    return tuple(
        _SkillTool(name, session)
        for name in (
            IntrinsicName.LIST_SKILLS,
            IntrinsicName.LOAD_SKILL,
            IntrinsicName.UNLOAD_SKILL,
            IntrinsicName.LIST_SKILL_RESOURCES,
            IntrinsicName.LOAD_SKILL_RESOURCE,
        )
    )


__all__ = ["LoadedSkill", "SkillSession", "skill_tools"]
