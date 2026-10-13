"""Assembling one process's harness from ``Settings`` (R21): the built-in plugin, the
operator's plugins, MCP tool sources, skills, the system prompt, the model, the store
and the in-process engine the activities run over."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from pydantic import SecretStr

from tiny_harness.builtin import load_builtin
from tiny_harness.config import Settings
from tiny_harness.harness.agents import SELF_AGENT_ID, Agent, RemoteAgent, build_roster
from tiny_harness.harness.channels.help import register_default as register_help_default
from tiny_harness.harness.commands import CommandHandler, CommandRegistry, CommandSpec
from tiny_harness.harness.core import ContextWindowManager
from tiny_harness.harness.core.inprocess import InProcessOperations
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.models import LLM, ModelCatalog, OpenAILLM
from tiny_harness.harness.persistence import RecordKind, SqliteStore, Store
from tiny_harness.harness.plugins import LoadReport, McpStdioServer, Plugin, PluginLoader
from tiny_harness.harness.plugins.loader import prepare_stdio
from tiny_harness.harness.plugins.registrar import RegistryRegistrar
from tiny_harness.harness.prompts.entity import SYSTEM_PROMPT_ID, PromptEntity, SystemPrompt
from tiny_harness.harness.security import Redactor
from tiny_harness.harness.skills.loader import skills_index
from tiny_harness.harness.tools.mcp import McpToolSource, ServerSpec
from tiny_harness.harness.tools.skill_tools import SkillSession, skill_tools
from tiny_harness.service.a2a.card import build_agent_card, describe
from tiny_harness.service.durable.models import WorkflowConfig
from tiny_harness.service.o11y.plugin import executor as o11y_executor
from tiny_harness.service.o11y.plugin import o11y_plugin

log = logging.getLogger("tiny_harness.runtime")


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
    commands: CommandRegistry  # filled before the worker starts, frozen when it does
    sources: list[McpToolSource] = field(default_factory=lambda: list[McpToolSource]())
    reports: list[LoadReport] = field(default_factory=lambda: list[LoadReport]())


def model_endpoint_line(llm: LLM) -> str | None:
    """Where model calls go, for the startup log: the origin only — never the path, the
    query or the key (issue-19 NFR observability, abuse case 5)."""
    info = llm.info
    if info.endpoint is None:
        return None
    return f"model endpoint {info.endpoint} api={info.api} model={info.model}"


# Variables an operator may still export that nothing reads; each is reported, never
# echoed (issue-19 R1.3, issue-23 R1.3).
IGNORED_VARIABLES = (
    ("OPENAI_BASE_URL", "the model endpoint is [openai] base_url"),
    (
        "TINY_HARNESS_PUSH_KEY",
        "push-notification credentials are protected at rest by the store",
    ),
)


def ignored_environment_warnings(env: Mapping[str, str]) -> tuple[str, ...]:
    """One line per ignored variable that is set, so none is ignored silently."""
    return tuple(
        f"{variable} is set and ignored; {reason}"
        for variable, reason in IGNORED_VARIABLES
        if env.get(variable)
    )


def secret_values(settings: Settings) -> list[SecretStr]:
    values: list[SecretStr] = []
    if settings.temporal.api_key is not None:  # absent in embedded mode (issue-17 R1.4)
        values.append(settings.temporal.api_key)
    if settings.openai.api_key is not None:  # absent for a keyless endpoint (issue-19 R2.2)
        values.append(settings.openai.api_key)
    if settings.anthropic is not None:
        values.append(settings.anthropic.api_key)
    for key in (settings.o11y.langfuse_public_key, settings.o11y.langfuse_secret_key):
        if key is not None:
            values.append(key)
    return values


def retention_map(settings: Settings) -> dict[RecordKind, timedelta]:
    config = settings.retention
    return {kind: getattr(config, kind.value) for kind in RecordKind}


def workflow_config(settings: Settings, *, agent: str | None = None) -> WorkflowConfig:
    return WorkflowConfig(
        agent=agent or settings.agent.id,
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
    builtin_commands: bool = True,
    plugins: Sequence[Plugin | Path] = (),
    commands: Iterable[tuple[CommandSpec, CommandHandler]] = (),
) -> Runtime:
    """Assemble the harness (issue-25 R11): ``plugins`` (a directory or a programmatic
    ``Plugin``) load after ``settings.plugins``, with the same override, and ``commands``
    register from code after every plugin; a bad or duplicate name raises
    ``CommandError`` (R6.5). ``builtin_commands=False`` builds without ``/model``,
    ``/effort``, ``/sub-task`` and ``/status`` (R6.8)."""
    registry = Registry()
    hooks = HookManager()
    registrar = RegistryRegistrar(registry)
    registered = CommandRegistry(hooks)  # plugins declare commands into it (issue-25 R6a.6)
    catalog = ModelCatalog.from_settings(settings)  # the selectable models and defaults (R7, R8)
    root = (data_root or settings.store.sqlite_path.resolve().parent / "plugin-data").resolve()
    reports = [
        await load_builtin(
            hook_manager=hooks,
            registrar=registrar,
            data_root=root,
            commands=registered,
            catalog=catalog if builtin_commands else None,
        )
    ]
    registrar.override = True
    loader = PluginLoader(
        hook_manager=hooks, registrar=registrar, data_root=root, commands=registered
    )
    redactor = Redactor(secrets=secret_values(settings))
    o11y_executor.redactor = redactor  # the plugin's one hook scrubs with the real secrets
    reports.append(await loader.load(o11y_plugin()))
    for path in settings.plugins:
        reports.append(await loader.load_directory(path, override=True))
    for plugin in plugins:
        if isinstance(plugin, Plugin):
            reports.append(await loader.load(plugin, override=True))
        else:
            reports.append(await loader.load_directory(plugin, override=True))
    for command, handler in commands:
        registered.register(command, handler)
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
    me = self_agent(settings)  # the harness delegates to itself over A2A (issue-34 R7.1)
    await registry.add(RegistryEntry(ref=me.ref, instance=me), override=True)
    for remote in settings.agents:
        agent = await RemoteAgent.connect(
            remote.id,
            str(remote.url),
            version=remote.version,
            updates=remote.updates,
            follow_interval=remote.follow_interval,
        )
        await registry.add(RegistryEntry(ref=agent.ref, instance=agent), override=True)
    roster = build_roster(await registered_agents(registry))  # once: a stable prefix (R1.5)
    log.info("agents roster: %s", ", ".join(roster.ids) or "(none)")
    for agent_id, card_field in roster.truncated:
        log.warning("agent %s: card field %s truncated in the agents roster", agent_id, card_field)
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
    for ignored in ignored_environment_warnings(os.environ):
        log.warning("%s", ignored)
    records = store or SqliteStore(settings.store.sqlite_path)
    engine = InProcessOperations(
        registry=registry,
        hooks=hooks,
        llm=model,
        store=records,
        system_prompt=system_prompt,
        skills_index=index,
        agents_roster=roster.text,
        manager=ContextWindowManager(
            turn_budget_tokens=settings.context.turn_budget_tokens,
            compaction_fraction=settings.context.compaction_fraction,
        ),
        redactor=redactor,
        catalog=catalog,
    )
    engine.sources = sources
    await engine.bind()
    register_help_default(hooks, model, catalog)
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
        commands=registered,
        sources=sources,
        reports=reports,
    )


def self_agent(settings: Settings) -> RemoteAgent:
    """This harness as an agent, ``self``: its own card at its own ``base_url``, reached
    over HTTP like any remote agent (issue-34 R7.1). The card is built, not fetched, so
    the server need not be up yet."""
    base_url = str(settings.server.base_url)
    return RemoteAgent.from_card(SELF_AGENT_ID, build_agent_card(describe(settings.card), base_url))


async def registered_agents(registry: Registry) -> list[Agent]:
    """One agent per id, sorted: the version a delegation reaches (``*``, the latest), so
    the roster describes the agent ``spawn_subtask`` will call (issue-34)."""
    ids = sorted({ref.id for ref in registry.list(EntityKind.AGENT)})
    return [
        await registry.get(EntityRef(kind=EntityKind.AGENT, id=agent_id, version="*"), Agent)
        for agent_id in ids
    ]


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
    "SELF_AGENT_ID",
    "Retention",
    "Runtime",
    "build_runtime",
    "registered_agents",
    "render_system_prompt",
    "retention_map",
    "secret_values",
    "self_agent",
    "workflow_config",
]
