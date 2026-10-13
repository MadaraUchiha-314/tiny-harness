"""The ``[agent]`` section (issue-36 R4.6, R5.3, R7.2): the agent's id defaults to
``tiny-harness``, the task queue defaults to the agent's id, and an explicit queue is kept."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiny_harness.config import DEFAULT_AGENT_ID, Settings
from tiny_harness.errors import ConfigError

ENV = {"OPENAI_API_KEY": "sk-secret"}

BASE = """
[temporal]
mode = "embedded"
{temporal}

[server]
base_url = "http://127.0.0.1:8080"
{tail}
"""


def load(tmp_path: Path, *, temporal: str = "", tail: str = "") -> Settings:
    path = tmp_path / "config.toml"
    path.write_text(BASE.format(temporal=temporal, tail=tail))
    return Settings.load(path, env=ENV)


def test_no_agent_section_keeps_todays_id_and_queue(tmp_path: Path) -> None:
    settings = load(tmp_path)
    assert settings.agent.id == DEFAULT_AGENT_ID == "tiny-harness"
    assert settings.temporal.task_queue == "tiny-harness"
    assert settings.temporal.effective_task_queue == "tiny-harness"


def test_the_queue_defaults_to_the_agent_id(tmp_path: Path) -> None:
    settings = load(tmp_path, tail='[agent]\nid = "billing"\nname = "Billing"')
    assert settings.agent.id == "billing"
    assert settings.agent.name == "Billing"
    assert settings.temporal.effective_task_queue == "billing"


def test_an_explicit_queue_is_kept(tmp_path: Path) -> None:
    settings = load(tmp_path, temporal='task_queue = "q1"', tail='[agent]\nid = "billing"')
    assert settings.temporal.effective_task_queue == "q1"


def test_the_demo_configuration_loads_unchanged() -> None:
    settings = Settings.load(Path("examples/demo/config.embedded.toml"), env=ENV)
    assert settings.agent.id == "tiny-harness"
    assert settings.temporal.effective_task_queue == "tiny-harness-demo"  # its own, kept


@pytest.mark.parametrize("bad", ["Billing", "-x", "a b", "", "x" * 64])
def test_a_bad_agent_id_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, tail=f'[agent]\nid = "{bad}"')
    assert caught.value.variable == "agent.id"
