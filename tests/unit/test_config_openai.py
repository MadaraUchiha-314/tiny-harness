"""The ``[openai]`` endpoint keys (issue-19 R1-R4): ``base_url`` points the adapter at any
OpenAI-compatible server, the key is optional only with it, ``api`` picks the wire API and
``context_window_tokens`` overrides the window; every bad value fails closed (abuse 2, 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from tiny_harness.config import OpenAIConfig, Settings
from tiny_harness.errors import ConfigError

ENV = {
    "OPENAI_API_KEY": "sk-secret",
    "TINY_HARNESS_PUSH_KEY": "cHVzaC1rZXk=",
}
KEYLESS_ENV = {k: v for k, v in ENV.items() if k != "OPENAI_API_KEY"}

CONFIG = """
[temporal]
mode = "embedded"

[server]
base_url = "http://127.0.0.1:8080"

[openai]
{openai}
"""


def load(tmp_path: Path, openai: str = "", *, env: dict[str, str] = ENV) -> Settings:
    path = tmp_path / "config.toml"
    path.write_text(CONFIG.format(openai=openai))
    return Settings.load(path, env=env)


def refused(tmp_path: Path, openai: str, *, env: dict[str, str] = ENV) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, openai, env=env)
    return caught.value


# R1 — the endpoint.


def test_defaults_keep_todays_configuration(tmp_path: Path) -> None:
    config = load(tmp_path).openai
    assert config.base_url is None
    assert config.api == "responses"
    assert config.context_window_tokens is None
    assert config.api_key is not None and config.api_key.get_secret_value() == "sk-secret"


def test_base_url_is_taken_from_the_file(tmp_path: Path) -> None:
    config = load(tmp_path, 'base_url = "https://openrouter.ai/api/v1"').openai
    assert str(config.base_url) == "https://openrouter.ai/api/v1"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://h/v1",
        "127.0.0.1:11434/v1",
        "not a url",
        "https:example.com",
        "http:/h/v1",
        "https://",
    ],
)
def test_a_base_url_that_is_not_absolute_http_is_refused(tmp_path: Path, url: str) -> None:
    error = refused(tmp_path, f'base_url = "{url}"')
    assert error.variable == "openai.base_url"


# R2 — the key is optional only with a custom endpoint.


def test_no_key_and_no_base_url_names_the_variable(tmp_path: Path) -> None:
    error = refused(tmp_path, "", env=KEYLESS_ENV)
    assert error.variable == "OPENAI_API_KEY"


def test_no_key_with_a_base_url_loads(tmp_path: Path) -> None:
    config = load(tmp_path, 'base_url = "http://127.0.0.1:11434/v1"', env=KEYLESS_ENV).openai
    assert config.api_key is None


def test_a_key_with_a_base_url_is_kept(tmp_path: Path) -> None:
    config = load(tmp_path, 'base_url = "https://openrouter.ai/api/v1"').openai
    assert config.api_key is not None and config.api_key.get_secret_value() == "sk-secret"


def test_a_config_built_in_code_needs_a_key_or_a_base_url() -> None:
    with pytest.raises(ValidationError):
        OpenAIConfig()


# R3.1 — the wire API.


@pytest.mark.parametrize("api", ["responses", "chat_completions"])
def test_both_wire_apis_are_accepted(tmp_path: Path, api: str) -> None:
    assert load(tmp_path, f'api = "{api}"').openai.api == api


def test_an_unknown_wire_api_is_refused(tmp_path: Path) -> None:
    assert refused(tmp_path, 'api = "chat"').variable == "openai.api"


# R4.3 — the context window.


def test_context_window_tokens_is_taken_from_the_file(tmp_path: Path) -> None:
    assert load(tmp_path, "context_window_tokens = 16384").openai.context_window_tokens == 16384


@pytest.mark.parametrize("value", ["0", "-1", '"big"', "true", "16384.0"])
def test_a_non_positive_context_window_is_refused(tmp_path: Path, value: str) -> None:
    error = refused(tmp_path, f"context_window_tokens = {value}")
    assert error.variable == "openai.context_window_tokens"


# Abuse case 2 — no key in clear text over a network.


@pytest.mark.parametrize(
    "url",
    ["http://10.0.0.5/v1", "http://ollama.lan:11434/v1", "http://localhost.evil.invalid/v1"],
)
def test_abuse_a_key_over_http_to_a_non_loopback_host_is_refused(tmp_path: Path, url: str) -> None:
    error = refused(tmp_path, f'base_url = "{url}"')
    assert error.variable == "openai.base_url"
    assert "sk-secret" not in str(error)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434/v1",
        "http://127.8.0.1/v1",
        "http://[::1]:11434/v1",
        "http://localhost:11434/v1",
    ],
)
def test_a_key_over_http_to_loopback_is_accepted(tmp_path: Path, url: str) -> None:
    assert load(tmp_path, f'base_url = "{url}"').openai.base_url is not None


def test_http_to_a_network_host_without_a_key_is_accepted(tmp_path: Path) -> None:
    config = load(tmp_path, 'base_url = "http://10.0.0.5:11434/v1"', env=KEYLESS_ENV).openai
    assert config.api_key is None


def test_abuse_the_http_rule_also_holds_for_a_config_built_in_code() -> None:
    with pytest.raises(ValidationError):
        OpenAIConfig.model_validate({"api_key": SecretStr("k"), "base_url": "http://10.0.0.5/v1"})


# Abuse case 3 — no credentials in the URL.


@pytest.mark.parametrize("url", ["http://u:p@127.0.0.1:11434/v1", "https://u@openrouter.ai/api/v1"])
def test_abuse_credentials_in_the_base_url_are_refused(tmp_path: Path, url: str) -> None:
    error = refused(tmp_path, f'base_url = "{url}"', env=KEYLESS_ENV)
    assert error.variable == "openai.base_url"


# The redactor's input (abuse case 5): the key is masked when set and skipped when absent.


def test_secret_values_include_the_key_only_when_it_is_set(tmp_path: Path) -> None:
    from tiny_harness.service.runtime import secret_values

    keyed = load(tmp_path, 'base_url = "https://openrouter.ai/api/v1"')
    keyless = load(tmp_path, 'base_url = "http://127.0.0.1:11434/v1"', env=KEYLESS_ENV)
    assert "sk-secret" in [v.get_secret_value() for v in secret_values(keyed)]
    assert [v.get_secret_value() for v in secret_values(keyless)] == ["cHVzaC1rZXk="]


# R6.1 — the shipped offline configuration.


def test_the_ollama_demo_configuration_loads_without_any_key() -> None:
    path = Path(__file__).resolve().parents[2] / "examples" / "demo" / "config.ollama.toml"
    settings = Settings.load(path, env=KEYLESS_ENV)
    assert settings.temporal.mode == "embedded"
    assert str(settings.openai.base_url) == "http://127.0.0.1:11434/v1"
    assert settings.openai.api_key is None and settings.openai.api == "chat_completions"
    assert settings.openai.context_window_tokens == 16384
