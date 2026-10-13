"""Remote agent update modes (issue-27 R4): ``updates`` and ``follow_interval`` per
``[[agents]]`` entry, with defaults that keep an existing entry loading unchanged (T10)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from tiny_harness.config import Settings
from tiny_harness.errors import ConfigError

ENV = {"OPENAI_API_KEY": "sk-secret"}

BASE = """
[temporal]
mode = "embedded"

[server]
base_url = "http://127.0.0.1:8080"

[store]
sqlite_path = "{store}"

[[agents]]
id = "ledger"
url = "http://ledger.example"
{extra}
"""


def load(tmp_path: Path, extra: str = "") -> Settings:
    path = tmp_path / "config.toml"
    path.write_text(BASE.format(store=tmp_path / "s.sqlite3", extra=extra))
    return Settings.load(path, env=ENV)


def test_an_entry_without_the_new_keys_loads_with_the_defaults(tmp_path: Path) -> None:
    (agent,) = load(tmp_path).agents
    assert agent.updates == "auto"
    assert agent.follow_interval == timedelta(seconds=5)


@pytest.mark.parametrize("mode", ["auto", "follow", "off"])
def test_each_update_mode_is_accepted(tmp_path: Path, mode: str) -> None:
    (agent,) = load(tmp_path, f'updates = "{mode}"').agents
    assert agent.updates == mode


def test_an_unknown_update_mode_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load(tmp_path, 'updates = "push"')
    assert info.value.variable == "agents.0.updates"


def test_a_follow_interval_below_one_second_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load(tmp_path, 'follow_interval = "PT0.5S"')
    assert info.value.variable == "agents.0.follow_interval"


def test_a_follow_interval_is_read(tmp_path: Path) -> None:
    (agent,) = load(tmp_path, 'follow_interval = "PT30S"').agents
    assert agent.follow_interval == timedelta(seconds=30)
