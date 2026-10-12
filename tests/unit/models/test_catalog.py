"""``ModelCatalog`` (issue-25 R7.1, R7.5, R8.1, R8.5): the selectable models, the default
model and effort, each model's context window, and the per-task settings a model call
uses — the task's choice first, the configured default otherwise."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import SecretStr

from tiny_harness.config import AnthropicConfig, OpenAIConfig, ReasoningEffort, Settings
from tiny_harness.harness.models.catalog import ModelCatalog
from tiny_harness.harness.models.openai_adapter import CONTEXT_WINDOWS


@dataclass(frozen=True)
class Chosen:
    """Stands in for the task extension's ``model`` / ``reasoning_effort`` (task 3)."""

    model: str | None = None
    reasoning_effort: ReasoningEffort | None = None


def openai(**values: object) -> OpenAIConfig:
    return OpenAIConfig.model_validate({"api_key": SecretStr("sk"), **values})


def test_without_models_the_default_is_the_only_selectable_model() -> None:
    catalog = ModelCatalog.from_config(openai(model="gpt-6-luna"))
    assert catalog.default == "gpt-6-luna"
    assert catalog.selectable == ("gpt-6-luna",)
    assert catalog.default_effort is None


def test_models_and_the_default_effort_come_from_the_configuration() -> None:
    catalog = ModelCatalog.from_config(
        openai(model="gpt-6.1-sol", models=["gpt-6-luna", "gpt-6.1-sol"], reasoning_effort="low")
    )
    assert catalog.selectable == ("gpt-6-luna", "gpt-6.1-sol")
    assert catalog.default_effort == "low"


def test_from_settings_uses_the_openai_provider(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[temporal]\nmode = "embedded"\n[server]\nbase_url = "http://127.0.0.1:8080"\n'
        '[openai]\nmodel = "gpt-6-astra"\nmodels = ["gpt-6-astra", "gpt-6-luna"]\n'
    )
    catalog = ModelCatalog.from_settings(Settings.load(path, env={"OPENAI_API_KEY": "sk"}))
    assert (catalog.default, catalog.selectable) == ("gpt-6-astra", ("gpt-6-astra", "gpt-6-luna"))


def test_the_context_window_is_the_adapters_table_with_a_fallback() -> None:
    catalog = ModelCatalog.from_config(openai(models=["gpt-6.1-sol", "gpt-6-luna", "local"]))
    assert catalog.context_window("gpt-6.1-sol") == CONTEXT_WINDOWS["gpt-6.1-sol"]
    assert catalog.context_window("gpt-6-luna") == CONTEXT_WINDOWS["gpt-6-luna"]
    assert catalog.context_window("local") == 400_000


def test_the_configured_window_overrides_the_table() -> None:
    catalog = ModelCatalog.from_config(openai(context_window_tokens=32_768))
    assert catalog.context_window("gpt-6.1-sol") == 32_768


def test_anthropic_uses_its_own_table() -> None:
    catalog = ModelCatalog.from_config(
        AnthropicConfig(api_key=SecretStr("sk"), model="claude-opus-5-5", reasoning_effort="high")
    )
    assert catalog.context_window("claude-opus-5-5") == 1_000_000
    assert catalog.context_window("claude-other") == 200_000
    assert catalog.default_effort == "high"


@pytest.mark.parametrize(
    ("chosen", "expected"),
    [
        (None, ("gpt-6.1-sol", "medium")),
        (Chosen(), ("gpt-6.1-sol", "medium")),
        (Chosen(model="gpt-6-luna"), ("gpt-6-luna", "medium")),
        (Chosen(reasoning_effort="high"), ("gpt-6.1-sol", "high")),
        (Chosen(model="gpt-6-luna", reasoning_effort="low"), ("gpt-6-luna", "low")),
    ],
)
def test_settings_for_prefers_the_tasks_choice(
    chosen: Chosen | None, expected: tuple[str, ReasoningEffort | None]
) -> None:
    catalog = ModelCatalog.from_config(
        openai(models=["gpt-6.1-sol", "gpt-6-luna"], reasoning_effort="medium")
    )
    assert catalog.settings_for(chosen) == expected


def test_settings_for_sends_no_effort_when_nothing_sets_one() -> None:
    """R8.5: no effort on the task or in the configuration → none on the request."""
    catalog = ModelCatalog.from_config(openai())
    assert catalog.settings_for(Chosen()) == ("gpt-6.1-sol", None)
