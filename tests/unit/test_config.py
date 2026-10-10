"""Configuration (R21): secrets from the environment, unknown keys rejected, typed defaults."""

from datetime import timedelta
from pathlib import Path

import pytest

from tiny_harness.config import RetryPolicySpec, Settings
from tiny_harness.errors import ConfigError

ENV = {
    "TEMPORAL_API_KEY": "tmprl_secret",
    "OPENAI_API_KEY": "sk-secret",
    "TINY_HARNESS_PUSH_KEY": "cHVzaC1rZXk=",
}

TOML = """
[temporal]
address = "tiny-harness.gtebu.tmprl.cloud:7233"
namespace = "tiny-harness.gtebu"

[server]
base_url = "https://harness.example.com"

[retries.per_activity.invoke_llm]
maximum_attempts = 3
"""


def write(tmp_path: Path, text: str = TOML) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_loads_toml_and_secrets_with_typed_defaults(tmp_path: Path) -> None:
    settings = Settings.load(write(tmp_path), env=ENV)
    assert settings.temporal.namespace == "tiny-harness.gtebu"
    assert settings.temporal.api_key.get_secret_value() == "tmprl_secret"
    assert settings.openai.model == "gpt-6.1-sol"
    assert settings.anthropic is None
    assert settings.heartbeat.interval == timedelta(seconds=30)
    assert settings.retries.for_activity("invoke_llm").maximum_attempts == 3
    assert settings.retries.for_activity("invoke_tool") == RetryPolicySpec()
    assert settings.context.turn_budget_tokens == 12_000
    assert settings.retention.tasks == timedelta(days=30)


def test_missing_secret_names_variable(tmp_path: Path) -> None:
    env = {k: v for k, v in ENV.items() if k != "OPENAI_API_KEY"}
    with pytest.raises(ConfigError) as info:
        Settings.load(write(tmp_path), env=env)
    assert info.value.variable == "OPENAI_API_KEY"
    assert "OPENAI_API_KEY" in str(info.value) and "sk-secret" not in str(info.value)


def test_unknown_key_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        Settings.load(
            write(
                tmp_path,
                TOML.replace(
                    'base_url = "https://harness.example.com"',
                    'base_url = "https://harness.example.com"\nmax_requests = 1',
                ),
            ),
            env=ENV,
        )
    assert "max_requests" in info.value.variable or "server" in info.value.variable


def test_secrets_never_print(tmp_path: Path) -> None:
    settings = Settings.load(write(tmp_path), env=ENV)
    dumped = settings.model_dump_json()
    assert "tmprl_secret" not in dumped and "sk-secret" not in dumped
    assert "**********" in repr(settings.temporal.api_key)


def test_optional_secrets_fill_their_sections(tmp_path: Path) -> None:
    env = dict(
        ENV, ANTHROPIC_API_KEY="ant-secret", LANGFUSE_PUBLIC_KEY="pk", LANGFUSE_SECRET_KEY="sk"
    )
    settings = Settings.load(write(tmp_path), env=env)
    assert settings.anthropic is not None and settings.anthropic.model == "claude-opus-5-5"
    assert settings.o11y.langfuse_public_key is not None


def test_missing_file_and_invalid_toml_are_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        Settings.load(tmp_path / "nope.toml", env=ENV)
    with pytest.raises(ConfigError):
        Settings.load(write(tmp_path, "[temporal\n"), env=ENV)
