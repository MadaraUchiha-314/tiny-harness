"""Typed, environment-driven configuration (Requirement 21).

Non-secret settings come from a TOML file (``examples/demo/config.toml`` for the demo);
every secret comes from an environment variable named below and nothing else
(``SecretStr``, never printed). Every model is ``extra="forbid"``, so an unknown key is
rejected (21.3), and a missing required secret fails at startup with the variable's name
(21.2). The retry, context and retention policies are configuration too, so a
deployment tunes them without code.
"""

from __future__ import annotations

import ipaddress
import math
import os
import re
import tomllib
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    StrictInt,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from tiny_harness.errors import ConfigError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


DEFAULT_AGENT_ID = "tiny-harness"


class AgentConfig(_Strict):
    """Who this agent is (issue-36 R4.6): its participant id on tasks, its default task
    queue and its heartbeat schedule. Several agents in one process each need their own id
    (R5.3). Its card's name and description are ``[card]``'s (issue-34)."""

    id: str = Field(
        default=DEFAULT_AGENT_ID,
        pattern=r"^[a-z0-9][a-z0-9-]{0,62}$",
        description="lowercase letters, digits and dashes; unique per process",
    )


class EmbeddedTemporalConfig(_Strict):
    """The local Temporal dev server of embedded mode (issue-17 R2-R4). Every key has a
    default, so ``mode = "embedded"`` alone is a complete Temporal configuration."""

    persist: bool = Field(
        default=True, description="false: an in-memory server, for tests and throwaway runs"
    )
    database_path: Path | None = Field(
        default=None, description="the server's SQLite file; default: beside store.sqlite_path"
    )
    binary_path: Path | None = Field(
        default=None, description="an existing Temporal CLI binary; set, nothing is downloaded"
    )
    download_dir: Path | None = Field(
        default=None,
        description="where a downloaded binary is cached; default: the user cache directory",
    )
    port: int | None = Field(
        default=None, ge=1, le=65535, description="default: an OS-chosen free port"
    )


class TemporalConfig(_Strict):
    """The Temporal connection (R19.11, issue-17). ``remote`` (the default) is Temporal Cloud
    or a self-hosted server, with ``api_key`` from ``TEMPORAL_API_KEY``; ``embedded`` starts a
    local dev server for the process and forbids the remote-only keys."""

    mode: Literal["remote", "embedded"] = "remote"
    address: str | None = Field(
        default=None, description="host:port, e.g. tiny-harness.gtebu.tmprl.cloud:7233"
    )
    namespace: str | None = Field(
        default=None, description="the Temporal namespace, e.g. tiny-harness.gtebu"
    )
    api_key: SecretStr | None = Field(
        default=None, description="from TEMPORAL_API_KEY; never logged"
    )
    task_queue: str | None = Field(
        default=None,
        description="the agent's Temporal task queue; default: the agent id ([agent] id), "
        "so two agents in one namespace never share one",
    )
    tls: bool = True
    search_attributes: bool = Field(
        default=False,
        description="use the A2AContextId, A2ATaskState and TinyHarnessAgent search attributes; "
        "they must be registered on the namespace first (Temporal Cloud: tcld), "
        "or every task workflow fails its first task",
    )
    embedded: EmbeddedTemporalConfig | None = None

    @model_validator(mode="after")
    def _per_mode(self) -> Self:
        if self.mode == "remote":
            for key in ("address", "namespace"):
                if getattr(self, key) is None:
                    raise ValueError(f"temporal.{key} is required when temporal.mode is remote")
            if self.embedded is not None:
                raise ValueError("temporal.embedded must not be set when temporal.mode is remote")
            return self
        for key in ("address", "api_key", "tls"):
            if key in self.model_fields_set:
                raise ValueError(f"temporal.{key} must not be set when temporal.mode is embedded")
        binary = self.embedded.binary_path if self.embedded is not None else None
        if binary is not None and not (binary.is_file() and os.access(binary, os.X_OK)):
            raise ValueError("temporal.embedded.binary_path is not an executable file")
        return self

    @property
    def effective_namespace(self) -> str:
        return self.namespace or "default"

    @property
    def effective_task_queue(self) -> str:
        """The queue this agent's workflows run on: ``task_queue``, else the agent id
        (``Settings`` fills it in; issue-36 R5.3)."""
        return self.task_queue or DEFAULT_AGENT_ID

    def database_path(self, store: StoreConfig) -> Path | None:
        """The embedded server's SQLite file, or ``None`` when it runs in memory."""
        embedded = self.embedded or EmbeddedTemporalConfig()
        if not embedded.persist:
            return None
        if embedded.database_path is not None:
            return embedded.database_path.resolve()
        return (store.sqlite_path.resolve().parent / "temporal.sqlite3").resolve()


_ABSOLUTE_HTTP_URL = re.compile(r"https?://[^/?#\s]+", re.IGNORECASE)


def _is_loopback_host(host: str) -> bool:
    """``localhost`` or a literal loopback address. Never resolved: what a name resolves to
    is what an attacker controls (issue-19 abuse case 2)."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


ReasoningEffort = Literal["low", "medium", "high"]
_Modality = Literal["text", "image", "audio"]


def _models_contain(models: tuple[str, ...] | None, info: ValidationInfo) -> tuple[str, ...] | None:
    """The selectable models must include the default (issue-25 R7.1): empty, or missing
    ``model``, fails closed."""
    if models is None:
        return models
    model = info.data.get("model")
    if not models or model not in models:
        raise ValueError(f"must be a non-empty list that contains model ({model!r})")
    return models


class OpenAIConfig(_Strict):
    """OpenAI, or any OpenAI-compatible server at ``base_url`` (R18.1, issue-19).

    ``api_key`` comes from ``OPENAI_API_KEY`` and may be absent only with a ``base_url``
    (a local server needs none). It is declared before ``base_url`` so the endpoint's
    validator can see it.
    """

    api_key: SecretStr | None = Field(default=None, description="from OPENAI_API_KEY; never logged")
    base_url: HttpUrl | None = Field(
        default=None,
        description="an OpenAI-compatible endpoint; default https://api.openai.com/v1",
    )
    api: Literal["responses", "chat_completions"] = "responses"
    model: str = "gpt-6.1-sol"
    models: tuple[str, ...] | None = Field(
        default=None, description="the models /model may select; default: model alone"
    )
    reasoning_effort: ReasoningEffort | None = Field(
        default=None, description="the default reasoning effort; default: none sent"
    )
    timeout: timedelta = timedelta(seconds=60)
    max_output_tokens: int = 2_000
    context_window_tokens: StrictInt | None = Field(
        default=None, gt=0, description="the model's window; default: the adapter's table"
    )
    input_modalities: tuple[_Modality, ...] | None = Field(
        default=None,
        description='what the model takes as input; default ["text", "image"] with '
        'api = "responses", ["text"] with chat_completions; add "audio" only for a '
        "Chat Completions audio model (issue-38)",
    )
    audio_tokens_per_second: StrictInt = Field(
        default=10, gt=0, description="tokens one second of native audio input costs"
    )

    _models = field_validator("models")(_models_contain)

    @field_validator("input_modalities")
    @classmethod
    def _text_and_known(cls, value: tuple[_Modality, ...] | None) -> tuple[_Modality, ...] | None:
        if value is None:
            return value
        if "text" not in value:
            raise ValueError('must include "text"')
        return tuple(dict.fromkeys(value))

    @field_validator("base_url", mode="before")
    @classmethod
    def _endpoint_is_absolute(cls, value: object) -> object:
        """``HttpUrl`` would normalize ``https:example.com`` into an absolute URL; R1.4 asks
        for one as written: ``http://`` or ``https://`` followed by a host."""
        if isinstance(value, str) and not _ABSOLUTE_HTTP_URL.match(value):
            raise ValueError("must be an absolute http:// or https:// URL")
        return value

    @field_validator("base_url")
    @classmethod
    def _endpoint_is_safe(cls, url: HttpUrl | None, info: ValidationInfo) -> HttpUrl | None:
        if url is None:
            return url
        if url.username is not None or url.password is not None:
            raise ValueError("must not carry credentials; OPENAI_API_KEY holds the key")
        key = info.data.get("api_key")
        if url.scheme == "http" and key is not None and not _is_loopback_host(url.host or ""):
            raise ValueError("must use https to send OPENAI_API_KEY to a non-loopback host")
        return url

    @model_validator(mode="after")
    def _key_or_endpoint(self) -> Self:
        if self.api_key is None and self.base_url is None:
            raise ValueError("api_key (OPENAI_API_KEY) is required unless base_url is set")
        return self

    @model_validator(mode="after")
    def _modalities_by_api(self) -> Self:
        """No ``input_modalities`` means what the wire API can carry today: images with
        Responses, text alone with Chat Completions, so a local model is not sent images
        unasked (issue-38)."""
        if self.input_modalities is None:
            self.input_modalities = ("text", "image") if self.api == "responses" else ("text",)
        return self


class AnthropicConfig(_Strict):
    """Anthropic through the Messages API; configurable, not exercised end to end (R21.4)."""

    api_key: SecretStr = Field(description="from ANTHROPIC_API_KEY; never logged")
    model: str
    models: tuple[str, ...] | None = Field(
        default=None, description="the models /model may select; default: model alone"
    )
    reasoning_effort: ReasoningEffort | None = Field(
        default=None, description="the default reasoning effort; default: none sent"
    )

    _models = field_validator("models")(_models_contain)


class RemoteAgentSpec(_Strict):
    """A remote A2A agent to register at startup (R7.2): its card is fetched from the URL.
    ``updates`` chooses how a parked remote task is watched between turns (issue-27 R4)."""

    id: str
    url: HttpUrl
    version: str | None = None
    updates: Literal["auto", "follow", "off"] = Field(
        default="auto",
        description="how a parked remote task's changes are heard: push when the card "
        "advertises it (auto), SubscribeToTask (follow), or not at all (off)",
    )
    follow_interval: timedelta = Field(
        default=timedelta(seconds=5),
        description="the pause before re-subscribing when a follow stream ends unchanged",
    )

    @field_validator("id")
    @classmethod
    def _not_self(cls, value: str) -> str:
        if value == "self":  # tiny_harness.harness.agents.SELF_AGENT_ID
            raise ValueError("the id self is reserved for this harness (issue-34 R7.1)")
        return value

    @field_validator("follow_interval")
    @classmethod
    def _at_least_a_second(cls, value: timedelta) -> timedelta:
        if value < timedelta(seconds=1):
            raise ValueError("follow_interval must be at least 1 second")
        return value


class CardSkillConfig(_Strict):
    """One skill this agent lists on its own card (issue-34 R5)."""

    id: str = Field(min_length=1, pattern=r"\S")
    name: str = Field(min_length=1, pattern=r"\S")
    description: str = ""
    tags: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


class CardConfig(_Strict):
    """This agent's own card (issue-34 R5): what another agent's roster shows about it.
    An unset field keeps the built-in default."""

    name: str | None = Field(default=None, min_length=1, pattern=r"\S")
    description: str | None = Field(
        default=None,
        min_length=1,
        pattern=r"\S",
        description="what this agent does; another agent reads it to decide when to delegate",
    )
    version: str | None = Field(default=None, min_length=1, pattern=r"\S")
    skills: tuple[CardSkillConfig, ...] = ()

    @field_validator("skills")
    @classmethod
    def _unique_ids(cls, skills: tuple[CardSkillConfig, ...]) -> tuple[CardSkillConfig, ...]:
        ids = [s.id for s in skills]
        if len(ids) != len(set(ids)):
            raise ValueError("each card skill id must be unique")
        return skills


class ServerConfig(_Strict):
    """The A2A server (R14). Bind and base URL, transport limits, the event bridge interval."""

    bind: str = "127.0.0.1:8080"
    base_url: HttpUrl = Field(
        description="the URL clients reach the server at; goes in the agent card"
    )
    max_request_bytes: int = 1_048_576
    rate_limit_per_minute: int = 120
    bridge_interval: timedelta = timedelta(milliseconds=250)
    cors_origins: tuple[str, ...] = ()
    delegators: tuple[str, ...] = Field(
        default=(),
        description="participant ids trusted to brief a new task fully (lifecycle, model, "
        "reasoning_effort) on its first message; this agent itself always is (issue-34 R7)",
    )
    ui_dir: Path | None = Field(
        default=None, description="a built web renderer to serve under /ui (R20.2)"
    )


class HeartbeatConfig(_Strict):
    """The heartbeat schedule (R16)."""

    interval: timedelta = timedelta(seconds=30)


class StoreConfig(_Strict):
    """The default SQLite store (R11.2)."""

    sqlite_path: Path = Path("tiny-harness.sqlite3")


class O11yConfig(_Strict):
    """Trace export (R17.5). The Langfuse keys come from ``LANGFUSE_PUBLIC_KEY`` and
    ``LANGFUSE_SECRET_KEY`` when set."""

    otlp_endpoint: HttpUrl | None = None
    langfuse_host: HttpUrl = HttpUrl("https://cloud.langfuse.com")
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    service_name: str = "tiny-harness"
    log_level: str = "INFO"
    trace_file: Path | None = Field(
        default=None, description="also write every finished span as one JSON line here"
    )


class MediaConfig(_Strict):
    """Images and audio in messages (issue-38). Absent, the instance is text-only, as
    before; present, it bounds every attachment (abuse case 1) and the request size."""

    max_file_bytes: StrictInt = Field(default=20_971_520, gt=0, description="20 MiB")
    max_message_bytes: StrictInt = Field(default=26_214_400, gt=0, description="25 MiB")
    max_image_pixels: StrictInt = Field(
        default=40_000_000, gt=0, description="width x height, read from the header"
    )
    max_audio_seconds: StrictInt = Field(default=120, gt=0)
    max_request_media_bytes: StrictInt = Field(
        default=20_971_520,
        gt=0,
        description="20 MiB; the media bytes one model request carries, newest first",
    )
    dir: Path | None = Field(
        default=None, description="where media is stored; default <sqlite dir>/media[-<agent>]"
    )
    speech_drain: timedelta = Field(
        default=timedelta(seconds=120),
        description="how long rollover or completion waits for spoken replies to finish",
    )

    @field_validator("dir", mode="before")
    @classmethod
    def _empty_is_default(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("speech_drain")
    @classmethod
    def _positive_drain(cls, value: timedelta) -> timedelta:
        if value <= timedelta(0):
            raise ValueError("speech_drain must be positive")
        return value

    @model_validator(mode="after")
    def _file_within_message(self) -> Self:
        if self.max_file_bytes > self.max_message_bytes:
            raise ValueError("max_file_bytes must not exceed max_message_bytes")
        return self

    def request_cap(self, max_request_bytes: int) -> int:
        """The request size the A2A routes admit: a full message of media, base64-encoded,
        plus a JSON envelope, or ``max_request_bytes`` when that is larger."""
        return max(max_request_bytes, math.ceil(self.max_message_bytes * 4 / 3) + 65_536)


class SpeechToTextConfig(_Strict):
    """Speech-to-text (issue-38 R5.3). Absent, audio goes to the model natively or is
    refused. ``openai`` uses ``[openai]``'s key and ``base_url``."""

    provider: Literal["openai"] = "openai"
    model: str = "gpt-4o-mini-transcribe"


class TextToSpeechConfig(_Strict):
    """Spoken replies (issue-38 R4, R5.3). Absent, replies are text only."""

    provider: Literal["openai"] = "openai"
    model: str = "gpt-4o-mini-tts"
    voice: str = "coral"
    instructions: str = Field(default="", description="an optional speaking style")


class ImageGenerationConfig(_Strict):
    """Images from the agent (issue-38 R2, R5.4). Absent, there is no generate_image tool."""

    provider: Literal["openai"] = "openai"
    model: str = "gpt-image-2"
    size: Literal["1024x1024", "1536x1024", "1024x1536"] = "1024x1024"


class RetryPolicySpec(BaseModel, frozen=True, extra="forbid"):
    """Workflow-managed retry policy for one activity (R19.3): Temporal's fields."""

    initial_interval: timedelta = timedelta(seconds=1)
    backoff_coefficient: float = 2.0
    maximum_interval: timedelta = timedelta(seconds=60)
    maximum_attempts: int = 5
    non_retryable_error_types: tuple[str, ...] = ()


class RetryPolicies(_Strict):
    """The default policy and per-activity overrides, keyed by activity name."""

    default: RetryPolicySpec = RetryPolicySpec()
    per_activity: Mapping[str, RetryPolicySpec] = Field(default_factory=dict)

    def for_activity(self, name: str) -> RetryPolicySpec:
        return self.per_activity.get(name, self.default)


class ContextConfig(_Strict):
    """Context window budget and compaction (R10.4) and the history bound (R19.8)."""

    turn_budget_tokens: int = 12_000
    compaction_fraction: float = 0.75
    history_event_bound: int = 10_000


class RetentionConfig(_Strict):
    """Time to live per store record kind (the personal-data boundary); 30 days by default."""

    tasks: timedelta = timedelta(days=30)
    plans: timedelta = timedelta(days=30)
    state: timedelta = timedelta(days=30)
    channel_messages: timedelta = timedelta(days=30)
    inbox_audit: timedelta = timedelta(days=30)
    compactions: timedelta = timedelta(days=30)
    push_configs: timedelta = timedelta(days=30)
    media: timedelta = timedelta(days=30)


class Settings(_Strict):
    """Everything a harness process needs. Built by ``load_settings``."""

    agent: AgentConfig = AgentConfig()
    temporal: TemporalConfig
    openai: OpenAIConfig
    anthropic: AnthropicConfig | None = None
    server: ServerConfig
    heartbeat: HeartbeatConfig = HeartbeatConfig()
    plugins: tuple[Path, ...] = ()
    agents: tuple[RemoteAgentSpec, ...] = ()
    card: CardConfig = CardConfig()
    store: StoreConfig = StoreConfig()
    o11y: O11yConfig = O11yConfig()
    retries: RetryPolicies = RetryPolicies()
    context: ContextConfig = ContextConfig()
    retention: RetentionConfig = RetentionConfig()
    media: MediaConfig | None = None
    speech_to_text: SpeechToTextConfig | None = None
    text_to_speech: TextToSpeechConfig | None = None
    image_generation: ImageGenerationConfig | None = None

    @model_validator(mode="after")
    def _media_sections_need_media(self) -> Self:
        """Speech and image providers handle media, so they need ``[media]`` (issue-38)."""
        if self.media is None:
            for section in ("speech_to_text", "text_to_speech", "image_generation"):
                if getattr(self, section) is not None:
                    raise ValueError(f"[{section}] requires [media]")
        return self

    @model_validator(mode="after")
    def _queue_from_agent(self) -> Self:
        """No ``task_queue`` means the agent's own queue (issue-36 R5.3, R7.2)."""
        if self.temporal.task_queue is None:
            self.temporal = self.temporal.model_copy(update={"task_queue": self.agent.id})
        return self

    @classmethod
    def load(cls, path: Path | None = None, *, env: Mapping[str, str] | None = None) -> Self:
        return load_settings(path, env=env, settings_type=cls)


# Secrets: (section, field, environment variable). Nothing else reads a secret.
SECRET_VARIABLES: tuple[tuple[str | None, str, str, bool], ...] = (
    ("temporal", "api_key", "TEMPORAL_API_KEY", True),  # remote mode only (issue-17 R1)
    ("openai", "api_key", "OPENAI_API_KEY", True),
    ("anthropic", "api_key", "ANTHROPIC_API_KEY", False),
    ("o11y", "langfuse_public_key", "LANGFUSE_PUBLIC_KEY", False),
    ("o11y", "langfuse_secret_key", "LANGFUSE_SECRET_KEY", False),
)


def _read_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError("configuration file not found", variable=str(path)) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"configuration file is not valid TOML: {exc}", variable=str(path)
        ) from exc


TEMPORAL_API_KEY = "TEMPORAL_API_KEY"
OPENAI_API_KEY = "OPENAI_API_KEY"
TEMPORAL_MODES = ("remote", "embedded")


def _temporal_mode(data: Mapping[str, object]) -> str:
    """The raw ``temporal.mode``, checked before secrets so a typo is reported as a typo
    (issue-17 R1.6) and never falls through to either mode."""
    section = data.get("temporal")
    mode = section.get("mode", "remote") if isinstance(section, dict) else "remote"  # type: ignore[union-attr]
    if mode not in TEMPORAL_MODES:
        raise ConfigError(
            "invalid configuration: temporal.mode must be 'remote' or 'embedded'",
            variable="temporal.mode",
        )
    return str(mode)  # type: ignore[arg-type]


def _openai_base_url_set(data: Mapping[str, object]) -> bool:
    """Whether the raw ``[openai]`` names an endpoint: then ``OPENAI_API_KEY`` is optional
    (issue-19 R2.2)."""
    section = data.get("openai")
    return isinstance(section, dict) and section.get("base_url") is not None  # type: ignore[union-attr]


def load_settings[S: Settings](
    path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    settings_type: type[S],
) -> S:
    """Read the TOML file (if any), add every secret from the environment, validate.

    A missing required secret is a ``ConfigError`` naming the variable; an unknown key or
    an invalid value is a ``ConfigError`` naming the key (21.2, 21.3). The process is
    expected to exit on either.
    """
    environment = os.environ if env is None else env
    data: dict[str, object] = _read_toml(path) if path is not None else {}
    embedded = _temporal_mode(data) == "embedded"
    keyless_ok = _openai_base_url_set(data)
    for section, field, variable, required in SECRET_VARIABLES:
        value = environment.get(variable)
        if variable == TEMPORAL_API_KEY and embedded:
            if value:
                raise ConfigError(
                    "must not be set when temporal.mode is embedded", variable=variable
                )
            continue
        if value is None or value == "":
            if required and not (variable == OPENAI_API_KEY and keyless_ok):
                raise ConfigError("required secret is not set", variable=variable)
            continue
        if section is None:
            data[field] = value
            continue
        existing = data.get(section)
        if section == "anthropic" and existing is None:
            existing = {"model": "claude-opus-5-5"}
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            raise ConfigError("configuration section must be a table", variable=section)
        table: dict[str, object] = {str(k): v for k, v in existing.items()}  # type: ignore[union-attr]
        table[field] = value
        data[section] = table
    try:
        return settings_type.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "<root>"
        raise ConfigError(f"invalid configuration: {first['msg']}", variable=location) from exc


__all__ = [
    "DEFAULT_AGENT_ID",
    "SECRET_VARIABLES",
    "AgentConfig",
    "AnthropicConfig",
    "CardConfig",
    "CardSkillConfig",
    "ContextConfig",
    "EmbeddedTemporalConfig",
    "HeartbeatConfig",
    "ImageGenerationConfig",
    "MediaConfig",
    "O11yConfig",
    "OpenAIConfig",
    "ReasoningEffort",
    "RemoteAgentSpec",
    "RetentionConfig",
    "RetryPolicies",
    "RetryPolicySpec",
    "ServerConfig",
    "Settings",
    "SpeechToTextConfig",
    "StoreConfig",
    "TemporalConfig",
    "TextToSpeechConfig",
    "load_settings",
]
