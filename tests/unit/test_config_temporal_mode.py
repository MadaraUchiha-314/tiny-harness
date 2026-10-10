"""Temporal mode (issue-17 R1, R3, R4): remote stays as it was, embedded needs no credentials
and refuses the remote-only keys, and a misspelled mode never means embedded."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from tiny_harness.config import Settings
from tiny_harness.errors import ConfigError

ENV = {
    "TEMPORAL_API_KEY": "tmprl_secret",
    "OPENAI_API_KEY": "sk-secret",
    "TINY_HARNESS_PUSH_KEY": "cHVzaC1rZXk=",
}
EMBEDDED_ENV = {k: v for k, v in ENV.items() if k != "TEMPORAL_API_KEY"}

REMOTE = """
[temporal]
address = "tiny-harness.gtebu.tmprl.cloud:7233"
namespace = "tiny-harness.gtebu"

[server]
base_url = "http://127.0.0.1:8080"
"""

EMBEDDED = """
[temporal]
mode = "embedded"
{temporal}

[server]
base_url = "http://127.0.0.1:8080"

[store]
sqlite_path = "{store}"
{tail}
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def embedded(tmp_path: Path, *, temporal: str = "", tail: str = "") -> Path:
    store = tmp_path / "state" / "tiny-harness.sqlite3"
    return write(tmp_path, EMBEDDED.format(temporal=temporal, store=store, tail=tail))


# R1.1, R1.2, R1.3 — remote is the default and keeps every requirement it had.


def test_absent_mode_is_remote_and_unchanged(tmp_path: Path) -> None:
    settings = Settings.load(write(tmp_path, REMOTE), env=ENV)
    assert settings.temporal.mode == "remote"
    assert settings.temporal.address == "tiny-harness.gtebu.tmprl.cloud:7233"
    assert settings.temporal.effective_namespace == "tiny-harness.gtebu"
    assert settings.temporal.api_key is not None
    assert settings.temporal.api_key.get_secret_value() == "tmprl_secret"


def test_remote_still_requires_the_api_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        Settings.load(write(tmp_path, REMOTE), env=EMBEDDED_ENV)
    assert info.value.variable == "TEMPORAL_API_KEY"


@pytest.mark.parametrize("key", ["address", "namespace"])
def test_remote_requires_address_and_namespace(tmp_path: Path, key: str) -> None:
    text = "\n".join(line for line in REMOTE.splitlines() if not line.startswith(key))
    with pytest.raises(ConfigError) as info:
        Settings.load(write(tmp_path, text), env=ENV)
    assert f"temporal.{key}" in info.value.message


def test_remote_refuses_the_embedded_table(tmp_path: Path) -> None:
    text = REMOTE.replace("[server]", "[temporal.embedded]\npersist = false\n\n[server]")
    with pytest.raises(ConfigError) as info:
        Settings.load(write(tmp_path, text), env=ENV)
    assert "temporal.embedded" in info.value.message


# R1.4, R1.7 — embedded needs no address and no key; namespace defaults.


def test_embedded_loads_without_address_or_key(tmp_path: Path) -> None:
    settings = Settings.load(embedded(tmp_path), env=EMBEDDED_ENV)
    assert settings.temporal.mode == "embedded"
    assert settings.temporal.address is None
    assert settings.temporal.api_key is None
    assert settings.temporal.effective_namespace == "default"
    assert settings.temporal.task_queue == "tiny-harness"


def test_embedded_keeps_namespace_and_task_queue(tmp_path: Path) -> None:
    path = embedded(tmp_path, temporal='namespace = "local"\ntask_queue = "q"')
    settings = Settings.load(path, env=EMBEDDED_ENV)
    assert settings.temporal.effective_namespace == "local"
    assert settings.temporal.task_queue == "q"


# R1.5, abuse case 2 — remote-only keys are refused in embedded mode, not ignored.


def test_embedded_refuses_the_api_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        Settings.load(embedded(tmp_path), env=ENV)
    assert info.value.variable == "TEMPORAL_API_KEY"
    assert "tmprl_secret" not in str(info.value)


@pytest.mark.parametrize(
    ("line", "key"),
    [('address = "localhost:7233"', "temporal.address"), ("tls = true", "temporal.tls")],
)
def test_embedded_refuses_remote_only_keys(tmp_path: Path, line: str, key: str) -> None:
    with pytest.raises(ConfigError) as info:
        Settings.load(embedded(tmp_path, temporal=line), env=EMBEDDED_ENV)
    assert key in info.value.message


# R1.6, abuse case 3 — any other mode is a typo, reported as one.


def test_misspelled_mode_is_reported_before_the_missing_key(tmp_path: Path) -> None:
    text = REMOTE.replace("[temporal]", '[temporal]\nmode = "embeded"')
    with pytest.raises(ConfigError) as info:
        Settings.load(write(tmp_path, text), env=EMBEDDED_ENV)
    assert info.value.variable == "temporal.mode"


# R3.1, R3.2, R3.4 — persistence beside the store by default, configurable, or off.


def test_database_defaults_beside_the_store(tmp_path: Path) -> None:
    settings = Settings.load(embedded(tmp_path), env=EMBEDDED_ENV)
    expected = (tmp_path / "state" / "temporal.sqlite3").resolve()
    assert settings.temporal.database_path(settings.store) == expected


def test_database_path_is_configurable(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere" / "t.sqlite3"
    path = embedded(tmp_path, tail=f'[temporal.embedded]\ndatabase_path = "{target}"')
    settings = Settings.load(path, env=EMBEDDED_ENV)
    assert settings.temporal.database_path(settings.store) == target.resolve()


def test_persist_false_means_no_database(tmp_path: Path) -> None:
    path = embedded(tmp_path, tail="[temporal.embedded]\npersist = false")
    settings = Settings.load(path, env=EMBEDDED_ENV)
    assert settings.temporal.database_path(settings.store) is None


# R4.1, R4.3, abuse case 4 — a configured binary must be an executable file.


def test_binary_path_must_exist(tmp_path: Path) -> None:
    missing = tmp_path / "no-temporal"
    path = embedded(tmp_path, tail=f'[temporal.embedded]\nbinary_path = "{missing}"')
    with pytest.raises(ConfigError) as info:
        Settings.load(path, env=EMBEDDED_ENV)
    assert "temporal.embedded.binary_path" in info.value.message


def test_binary_path_must_be_executable(tmp_path: Path) -> None:
    binary = tmp_path / "temporal"
    binary.write_text("not executable")
    binary.chmod(0o644)
    path = embedded(tmp_path, tail=f'[temporal.embedded]\nbinary_path = "{binary}"')
    with pytest.raises(ConfigError) as info:
        Settings.load(path, env=EMBEDDED_ENV)
    assert "temporal.embedded.binary_path" in info.value.message


def test_executable_binary_path_is_accepted(tmp_path: Path) -> None:
    binary = tmp_path / "temporal"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    path = embedded(tmp_path, tail=f'[temporal.embedded]\nbinary_path = "{binary}"')
    settings = Settings.load(path, env=EMBEDDED_ENV)
    assert settings.temporal.embedded is not None
    assert settings.temporal.embedded.binary_path == binary


# The secret list the redactor uses tolerates an absent Temporal key.


def test_secret_values_skip_the_absent_temporal_key(tmp_path: Path) -> None:
    from tiny_harness.service.runtime import secret_values

    settings = Settings.load(embedded(tmp_path), env=EMBEDDED_ENV)
    values = [value.get_secret_value() for value in secret_values(settings)]
    assert values == ["sk-secret", "cHVzaC1rZXk="]


# R6.4 — the demo ships an embedded configuration that needs no Temporal account.


def test_the_demo_embedded_config_loads_without_a_temporal_key() -> None:
    demo = Path(__file__).resolve().parents[2] / "examples" / "demo" / "config.embedded.toml"
    settings = Settings.load(demo, env=EMBEDDED_ENV)
    assert settings.temporal.mode == "embedded"
    assert settings.temporal.address is None and settings.temporal.api_key is None
