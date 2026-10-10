"""The CLI (R21): argument parsing and the fail-closed configuration path."""

from __future__ import annotations

from pathlib import Path

import pytest

from tiny_harness.service.cli import CONFIG_EXIT, build_parser, main

TOML = """
[temporal]
address = "tiny-harness.gtebu.tmprl.cloud:7233"
namespace = "tiny-harness.gtebu"

[openai]
model = "gpt-6.1-sol"

[server]
base_url = "http://127.0.0.1:8080"
"""


def test_every_command_parses() -> None:
    parser = build_parser()
    assert parser.parse_args(["serve", "--with-worker"]).with_worker is True
    assert parser.parse_args(["worker"]).command == "worker"
    assert parser.parse_args(["tui", "--url", "http://x"]).url == "http://x"
    assert parser.parse_args(["schedules", "delete"]).schedules_command == "delete"
    purge = parser.parse_args(["--config", "c.toml", "tasks", "purge", "t-1"])
    assert purge.task_id == "t-1" and purge.config == Path("c.toml")
    with pytest.raises(SystemExit):
        parser.parse_args(["bogus"])


def test_missing_secret_exits_non_zero_with_the_variable_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.toml"
    config.write_text(TOML)
    for variable in ("TEMPORAL_API_KEY", "OPENAI_API_KEY", "TINY_HARNESS_PUSH_KEY"):
        monkeypatch.delenv(variable, raising=False)
    assert main(["--config", str(config), "worker"]) == CONFIG_EXIT
    assert "TEMPORAL_API_KEY" in capsys.readouterr().err
