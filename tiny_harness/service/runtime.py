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

from a2a.types import AgentCard
from pydantic import SecretStr

from tiny_harness.builtin import load_builtin
from tiny_harness.config import DEFAULT_AGENT_ID, Settings
from tiny_harness.harness.agents import SELF_AGENT_ID, Agent, RemoteAgent, build_roster
from tiny_harness.harness.channels.help import register_default as register_help_default
from tiny_harness.harness.commands import CommandHandler, CommandRegistry, CommandSpec
from tiny_harness.harness.core import ContextWindowManager
from tiny_harness.harness.core.inprocess import InProcessOperations
from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.hooks import HookManager
from tiny_harness.harness.media import (
    FileMediaStore,
    MediaCapabilities,
    MediaIntake,
    MediaStore,
    capabilities,
)
from tiny_harness.harness.models import (
    LLM,
    ImageGenerator,
    ModelCatalog,
    OpenAIImageGenerator,
    OpenAILLM,
    OpenAISpeechToText,
    OpenAITextToSpeech,
    SpeechToText,
    TextToSpeech,
)
from tiny_harness.harness.models.openai_adapter import openai_client
from tiny_harness.harness.persistence import RecordKind, SqliteStore, Store
from tiny_harness.harness.plugins import LoadReport, McpStdioServer, Plugin, PluginLoader
from tiny_harness.harness.plugins.loader import prepare_stdio
from tiny_harness.harness.plugins.registrar import RegistryRegistrar
from tiny_harness.harness.prompts.entity import SYSTEM_PROMPT_ID, PromptEntity, SystemPrompt
from tiny_harness.harness.security import PROCESS_SECRETS, Redactor
from tiny_harness.harness.skills.loader import skills_index
from tiny_harness.harness.tools.mcp import McpToolSource, ServerSpec
from tiny_harness.harness.tools.skill_tools import SkillSession, skill_tools
from tiny_harness.service.a2a.card import AgentDescription, build_agent_card, describe
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
    # Media (issue-38): all None on a text-only instance (no [media] and no seams).
    media_store: MediaStore | None = None
    media_intake: MediaIntake | None = None
    speech_to_text: SpeechToText | None = None
    text_to_speech: TextToSpeech | None = None
    image_generator: ImageGenerator | None = None
    media: MediaCapabilities = field(default_factory=MediaCapabilities)


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


def default_data_root(settings: Settings) -> Path:
    """Where plugins and skills keep their data: ``plugin-data`` beside the store for the
    default agent (as before), ``plugin-data-<id>`` for any other, so two agents whose
    stores share a folder never share plugin data (issue-36 R5, critic round 1, #1)."""
    folder = settings.store.sqlite_path.resolve().parent
    if settings.agent.id == DEFAULT_AGENT_ID:
        return folder / "plugin-data"
    return folder / f"plugin-data-{settings.agent.id}"


def default_media_root(settings: Settings) -> Path:
    """Where media is stored (issue-38): ``[media] dir``, else ``media`` beside the store
    for the default agent and ``media-<id>`` for any other, as ``default_data_root``."""
    if settings.media is not None and settings.media.dir is not None:
        return settings.media.dir
    folder = settings.store.sqlite_path.resolve().parent
    if settings.agent.id == DEFAULT_AGENT_ID:
        return folder / "media"
    return folder / f"media-{settings.agent.id}"


MediaEntities = tuple[SpeechToText | None, TextToSpeech | None, ImageGenerator | None]


def build_media_entities(settings: Settings) -> MediaEntities:
    """Speech-to-text, text-to-speech and image generation from their sections, each
    ``None`` when its section is absent. ``provider = "openai"`` (the only one today)
    reuses ``[openai]``'s key and ``base_url`` over one client from the LLM adapter's
    factory; a new provider adds a literal and a branch here."""
    if not (settings.speech_to_text or settings.text_to_speech or settings.image_generation):
        return None, None, None
    config = settings.openai
    base_url = str(config.base_url) if config.base_url is not None else None
    client = openai_client(config.api_key, base_url=base_url, timeout=config.timeout)
    stt = tts = images = None
    if (section := settings.speech_to_text) is not None:
        stt = OpenAISpeechToText(
            config.api_key, model=section.model, base_url=base_url, client=client
        )
    if (section := settings.text_to_speech) is not None:
        tts = OpenAITextToSpeech(
            config.api_key,
            model=section.model,
            voice=section.voice,
            instructions=section.instructions,
            base_url=base_url,
            client=client,
        )
    if (section := settings.image_generation) is not None:
        images = OpenAIImageGenerator(
            config.api_key, model=section.model, size=section.size, base_url=base_url, client=client
        )
    return stt, tts, images


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
        speech_drain=(
            settings.media.speech_drain
            if settings.media is not None
            else WorkflowConfig.model_fields["speech_drain"].default
        ),
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
    public_url: str | None = None,
    description: AgentDescription | None = None,
    local_cards: Mapping[str, AgentCard] | None = None,
    speech_to_text: SpeechToText | None = None,
    text_to_speech: TextToSpeech | None = None,
    image_generator: ImageGenerator | None = None,
    media_store: MediaStore | None = None,
) -> Runtime:
    """Assemble the harness (issue-25 R11): ``plugins`` (a directory or a programmatic
    ``Plugin``) load after ``settings.plugins``, with the same override, and ``commands``
    register from code after every plugin; a bad or duplicate name raises
    ``CommandError`` (R6.5). ``builtin_commands=False`` builds without ``/model``,
    ``/effort``, ``/sub-task`` and ``/status`` (R6.8). ``public_url`` and ``description``
    are this harness's own (default: ``base_url`` and ``[card]``). A remote agent whose URL
    is a key of ``local_cards`` (a harness of this process) gets that card, unfetched
    (issue-36 R6.1). ``speech_to_text``, ``text_to_speech``, ``image_generator`` and
    ``media_store`` replace what ``[speech_to_text]``, ``[text_to_speech]``,
    ``[image_generation]`` and ``[media]`` would build, as ``llm`` replaces ``[openai]``
    (issue-38)."""
    local_cards = local_cards or {}
    registry = Registry()
    hooks = HookManager()
    registrar = RegistryRegistrar(registry)
    registered = CommandRegistry(hooks)  # plugins declare commands into it (issue-25 R6a.6)
    catalog = ModelCatalog.from_settings(settings)  # the selectable models and defaults (R7, R8)
    root = (data_root or default_data_root(settings)).resolve()
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
    redactor = Redactor(secrets=secret_values(settings), registry=PROCESS_SECRETS)
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
    # the harness delegates to itself over A2A (issue-34 R7.1), at its mounted URL (issue-36)
    me = self_agent(settings, public_url=public_url, description=description)
    await registry.add(RegistryEntry(ref=me.ref, instance=me), override=True)
    for remote in settings.agents:
        local = local_cards.get(str(remote.url).rstrip("/"))
        if local is not None:
            # A harness of this same process: it is not listening while the process starts,
            # so its card is built from its settings, as this harness's own is (issue-36 R6.1).
            log.info("agent %s is in this process; its card is built, not fetched", remote.id)
            agent = RemoteAgent.from_card(
                remote.id,
                local,
                version=remote.version,
                updates=remote.updates,
                follow_interval=remote.follow_interval,
            )
        else:
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
        input_modalities=openai_config.input_modalities,
    )
    line = model_endpoint_line(model)
    if line is not None:
        log.info("%s", line)
    for ignored in ignored_environment_warnings(os.environ):
        log.warning("%s", ignored)
    records = store or SqliteStore(settings.store.sqlite_path)
    configured = build_media_entities(settings)
    stt = speech_to_text or configured[0]
    tts = text_to_speech or configured[1]
    images = image_generator or configured[2]
    if media_store is None and settings.media is not None:
        media_store = FileMediaStore(
            EntityRef(kind=EntityKind.MEDIA_STORE, id="file"),
            default_media_root(settings).resolve(),
        )
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
            audio_tokens_per_second=settings.openai.audio_tokens_per_second,
        ),
        redactor=redactor,
        catalog=catalog,
        media_store=media_store,
        speech_to_text=stt,
        text_to_speech=tts,
        image_generator=images,
        media_base_url=public_url or str(settings.server.base_url),
    )
    engine.sources = sources
    await engine.bind()
    register_help_default(hooks, model, catalog)
    media = capabilities(model.info, stt, tts, images, settings.media)
    intake = None
    if settings.media is not None and media_store is not None:
        intake = MediaIntake(
            media_store,
            settings.media,
            base_url=public_url or str(settings.server.base_url),
            accepted=media.input,
        )
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
        media_store=media_store,
        media_intake=intake,
        speech_to_text=stt,
        text_to_speech=tts,
        image_generator=images,
        media=media,
    )


def self_agent(
    settings: Settings,
    *,
    public_url: str | None = None,
    description: AgentDescription | None = None,
) -> RemoteAgent:
    """This harness as an agent, ``self``: its own card at its own URL, reached over HTTP
    like any remote agent (issue-34 R7.1). The card is built, not fetched, so the server
    need not be up yet. ``public_url`` is where a mounted harness is served (issue-36)."""
    url = public_url or str(settings.server.base_url)
    return RemoteAgent.from_card(
        SELF_AGENT_ID, build_agent_card(description or describe(settings.card), url)
    )


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
    "MediaEntities",
    "Retention",
    "Runtime",
    "build_media_entities",
    "build_runtime",
    "default_data_root",
    "default_media_root",
    "registered_agents",
    "render_system_prompt",
    "retention_map",
    "secret_values",
    "self_agent",
    "workflow_config",
]
