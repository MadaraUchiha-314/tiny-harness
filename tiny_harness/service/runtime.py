"""Assembling one process's harness from ``Settings`` (R21): the built-in plugin, the
operator's plugins, MCP tool sources, skills, the system prompt, the model, the store
and the in-process engine the activities run over."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from pydantic import SecretStr

from tiny_harness.builtin import load_builtin
from tiny_harness.config import Settings
from tiny_harness.harness.agents import RemoteAgent
from tiny_harness.harness.channels.help import register_default as register_help_default
from tiny_harness.harness.core import ContextWindowManager
from tiny_harness.harness.core.inprocess import InProcessOperations
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.models import LLM, OpenAILLM
from tiny_harness.harness.persistence import RecordKind, SqliteStore, Store
from tiny_harness.harness.plugins import LoadReport, McpStdioServer, PluginLoader
from tiny_harness.harness.plugins.loader import prepare_stdio
from tiny_harness.harness.plugins.registrar import RegistryRegistrar
from tiny_harness.harness.prompts.entity import SYSTEM_PROMPT_ID, PromptEntity, SystemPrompt
from tiny_harness.harness.security import Redactor
from tiny_harness.harness.skills.loader import skills_index
from tiny_harness.harness.tools.mcp import McpToolSource, ServerSpec
from tiny_harness.harness.tools.skill_tools import SkillSession, skill_tools
from tiny_harness.service.durable.models import WorkflowConfig
from tiny_harness.service.o11y.plugin import executor as o11y_executor
from tiny_harness.service.o11y.plugin import o11y_plugin

log = logging.getLogger("tiny_harness.runtime")

AGENT_ID = "tiny-harness"


@dataclass
class Runtime:
    settings: Settings
    registry: Registry
    hooks: HookManager
    llm: LLM
    store: Store
    engine: InProcessOperations
    skills: SkillSession
    system_prompt: str
    redactor: Redactor
    sources: list[McpToolSource] = field(default_factory=lambda: list[McpToolSource]())
    reports: list[LoadReport] = field(default_factory=lambda: list[LoadReport]())


def model_endpoint_line(llm: LLM) -> str | None:
    """Where model calls go, for the startup log: the origin only — never the path, the
    query or the key (issue-19 NFR observability, abuse case 5)."""
    info = llm.info
    if info.endpoint is None:
        return None
    return f"model endpoint {info.endpoint} api={info.api} model={info.model}"


def secret_values(settings: Settings) -> list[SecretStr]:
    values = [settings.push_key]
    if settings.openai.api_key is not None:  # absent for a keyless endpoint (issue-19 R2.2)
        values.insert(0, settings.openai.api_key)
    if settings.temporal.api_key is not None:  # absent in embedded mode (issue-17 R1.4)
        values.insert(0, settings.temporal.api_key)
    if settings.anthropic is not None:
        values.append(settings.anthropic.api_key)
    for key in (settings.o11y.langfuse_public_key, settings.o11y.langfuse_secret_key):
        if key is not None:
            values.append(key)
    return values


def retention_map(settings: Settings) -> dict[RecordKind, timedelta]:
    config = settings.retention
    return {kind: getattr(config, kind.value) for kind in RecordKind}


def workflow_config(settings: Settings, *, agent: str = AGENT_ID) -> WorkflowConfig:
    return WorkflowConfig(
        agent=agent,
        retries=settings.retries,
        history_event_bound=settings.context.history_event_bound,
        search_attributes=settings.temporal.search_attributes,
    )


async def build_runtime(
    settings: Settings,
    *,
    llm: LLM | None = None,
    store: Store | None = None,
    data_root: Path | None = None,
) -> Runtime:
    registry = Registry()
    hooks = HookManager()
    registrar = RegistryRegistrar(registry)
    root = (data_root or settings.store.sqlite_path.resolve().parent / "plugin-data").resolve()
    reports = [await load_builtin(hook_manager=hooks, registrar=registrar, data_root=root)]
    registrar.override = True
    loader = PluginLoader(hook_manager=hooks, registrar=registrar, data_root=root)
    redactor = Redactor(secrets=secret_values(settings))
    o11y_executor.redactor = redactor  # the plugin's one hook scrubs with the real secrets
    reports.append(await loader.load(o11y_plugin()))
    for path in settings.plugins:
        reports.append(await loader.load_directory(path, override=True))
    sources: list[McpToolSource] = []
    for name, (plugin, server) in registrar.catalog.servers.items():
        spec: ServerSpec
        if isinstance(server, McpStdioServer):
            plugin_root = plugin.root or Path.cwd()
            spec = prepare_stdio(server, root=plugin_root, data=root / plugin.manifest.name)
        else:
            spec = str(server.url)
        source = McpToolSource(name, spec, version=plugin.manifest.version)
        for tool in await source.tools():
            await registry.add(RegistryEntry(ref=tool.ref, instance=tool), override=True)
        sources.append(source)
    for remote in settings.agents:
        agent = await RemoteAgent.connect(remote.id, str(remote.url), version=remote.version)
        await registry.add(RegistryEntry(ref=agent.ref, instance=agent), override=True)
    skills = SkillSession(registry, data_root=root)
    for tool in skill_tools(skills):
        await registry.add(RegistryEntry(ref=tool.ref, instance=tool), override=True)
    system_prompt = await render_system_prompt(registry)
    index = skills_index(await skills.skills())
    openai_config = settings.openai
    base_url = str(openai_config.base_url) if openai_config.base_url is not None else None
    model = llm or OpenAILLM(
        openai_config.api_key,
        model=openai_config.model,
        timeout=openai_config.timeout,
        max_output_tokens=openai_config.max_output_tokens,
        base_url=base_url,
        api=openai_config.api,
        context_window_tokens=openai_config.context_window_tokens,
    )
    line = model_endpoint_line(model)
    if line is not None:
        log.info("%s", line)
    records = store or SqliteStore(settings.store.sqlite_path)
    engine = InProcessOperations(
        registry=registry,
        hooks=hooks,
        llm=model,
        store=records,
        system_prompt=system_prompt,
        skills_index=index,
        manager=ContextWindowManager(
            turn_budget_tokens=settings.context.turn_budget_tokens,
            compaction_fraction=settings.context.compaction_fraction,
        ),
        redactor=redactor,
    )
    engine.sources = sources
    await engine.bind()
    register_help_default(hooks, model)
    return Runtime(
        settings=settings,
        registry=registry,
        hooks=hooks,
        llm=model,
        store=records,
        engine=engine,
        skills=skills,
        system_prompt=system_prompt,
        redactor=redactor,
        sources=sources,
        reports=reports,
    )


async def render_system_prompt(registry: Registry) -> str:
    """The built-in system prompt extended by every prompt that declares ``extends``."""
    base = await registry.get(EntityRef(kind=EntityKind.PROMPT, id=SYSTEM_PROMPT_ID), PromptEntity)
    extensions: list[PromptEntity] = []
    for ref in registry.list(EntityKind.PROMPT):
        if ref.id == SYSTEM_PROMPT_ID:
            continue
        prompt = await registry.get(ref, PromptEntity)
        if prompt.extends is not None:
            extensions.append(prompt)
    return SystemPrompt(base, extensions).render()


Retention = Mapping[RecordKind, timedelta]

__all__ = [
    "AGENT_ID",
    "Retention",
    "Runtime",
    "build_runtime",
    "render_system_prompt",
    "retention_map",
    "secret_values",
    "workflow_config",
]
