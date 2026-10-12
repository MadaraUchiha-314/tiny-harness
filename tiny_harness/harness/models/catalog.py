"""The models a task may use and how hard they think (issue-25 R7, R8).

``ModelCatalog`` is built from the provider configuration in use: the default model, the
selectable models (``/model`` checks membership with an exact compare), the default
reasoning effort and each model's context window. ``settings_for`` is the one place a
model call learns its model and effort: the task's choice, else the configured default.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, Self

from pydantic import BaseModel, Field

from tiny_harness.config import AnthropicConfig, OpenAIConfig, ReasoningEffort, Settings
from tiny_harness.harness.models import anthropic_adapter, openai_adapter

OPENAI_FALLBACK_WINDOW = 400_000
ANTHROPIC_FALLBACK_WINDOW = 200_000


class ModelChoice(Protocol):
    """What a task chose, if anything: the task extension's ``model`` and
    ``reasoning_effort``. ``None`` means "use the default"."""

    @property
    def model(self) -> str | None: ...

    @property
    def reasoning_effort(self) -> ReasoningEffort | None: ...


class ModelCatalog(BaseModel, frozen=True, extra="forbid"):
    default: str
    selectable: tuple[str, ...]
    default_effort: ReasoningEffort | None = None
    windows: Mapping[str, int] = Field(default_factory=dict)
    fallback_window: int = OPENAI_FALLBACK_WINDOW
    window_override: int | None = None

    @classmethod
    def from_config(cls, config: OpenAIConfig | AnthropicConfig) -> Self:
        """The catalog of one provider's configuration; ``models`` unset selects only
        ``model`` (R7.1)."""
        if isinstance(config, OpenAIConfig):
            windows, fallback = openai_adapter.CONTEXT_WINDOWS, OPENAI_FALLBACK_WINDOW
            override = config.context_window_tokens
        else:
            windows, fallback = anthropic_adapter.CONTEXT_WINDOWS, ANTHROPIC_FALLBACK_WINDOW
            override = None
        return cls(
            default=config.model,
            selectable=config.models or (config.model,),
            default_effort=config.reasoning_effort,
            windows=dict(windows),
            fallback_window=fallback,
            window_override=override,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """The catalog of the provider ``build_runtime`` uses: ``[openai]``."""
        return cls.from_config(settings.openai)

    def context_window(self, model: str) -> int:
        """The model's window: ``context_window_tokens`` when configured, else the
        adapter's table, else the adapter's fallback."""
        if self.window_override is not None:
            return self.window_override
        return self.windows.get(model, self.fallback_window)

    def settings_for(self, chosen: ModelChoice | None) -> tuple[str, ReasoningEffort | None]:
        """``(model, effort)`` for a model call of a task: its choice, else the defaults
        (R7.5). The effort stays ``None`` when neither sets one (R8.5)."""
        model = chosen.model if chosen is not None else None
        effort = chosen.reasoning_effort if chosen is not None else None
        return model or self.default, effort or self.default_effort


__all__ = ["ModelCatalog", "ModelChoice"]
