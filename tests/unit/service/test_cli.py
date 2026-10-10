"""The CLI (R21): argument parsing and the fail-closed configuration path."""

from __future__ import annotations

import getpass
from pathlib import Path

import pytest

from tiny_harness.service.cli import (
    CONFIG_EXIT,
    EMBEDDED_EXIT,
    SIGTERM_EXIT,
    build_parser,
    main,
    tui_participant,
)

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


# issue-17: embedded mode per command (R5.2, R5.5, R2.4) and signal routing (R2.3).

EMBEDDED = """
[temporal]
mode = "embedded"
{extra}

[openai]
model = "gpt-6.1-sol"

[server]
base_url = "http://127.0.0.1:8080"

[store]
sqlite_path = "{store}"
"""


def embedded_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str = "") -> Path:
    config = tmp_path / "config.toml"
    config.write_text(EMBEDDED.format(extra=extra, store=tmp_path / "state" / "db.sqlite3"))
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("TINY_HARNESS_PUSH_KEY", "cHVzaC1rZXk=")
    return config


def test_worker_is_refused_in_embedded_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = embedded_config(tmp_path, monkeypatch)
    assert main(["--config", str(config), "worker"]) == CONFIG_EXIT
    assert "in embedded mode the worker runs inside serve" in capsys.readouterr().err


@pytest.mark.parametrize("command", [["schedules", "delete"], ["tasks", "purge", "t-1"]])
def test_admin_commands_are_refused_on_in_memory_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: list[str],
) -> None:
    config = embedded_config(tmp_path, monkeypatch, "\n[temporal.embedded]\npersist = false")
    assert main(["--config", str(config), *command]) == CONFIG_EXIT
    assert "in-memory" in capsys.readouterr().err


def test_embedded_api_key_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = embedded_config(tmp_path, monkeypatch)
    monkeypatch.setenv("TEMPORAL_API_KEY", "tmprl_secret")
    assert main(["--config", str(config), "serve"]) == CONFIG_EXIT
    err = capsys.readouterr().err
    assert "TEMPORAL_API_KEY" in err and "tmprl_secret" not in err


def test_embedded_start_failure_exits_one_with_the_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tiny_harness.errors import EmbeddedTemporalError
    from tiny_harness.service import commands

    async def failing(*_: object, **__: object) -> int:
        raise EmbeddedTemporalError("port 7233 already in use")

    monkeypatch.setattr(commands, "serve", failing)
    config = embedded_config(tmp_path, monkeypatch)
    assert main(["--config", str(config), "serve"]) == EMBEDDED_EXIT
    assert "embedded Temporal failed to start: port 7233 already in use" in capsys.readouterr().err


def test_sigterm_cancels_the_command_so_its_cleanup_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import os
    import signal

    from tiny_harness.service import commands

    cleaned: list[str] = []

    async def long_running(*_: object, **__: object) -> int:
        try:
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(30)
            return 0
        finally:
            cleaned.append("finally ran")

    monkeypatch.setattr(commands, "serve", long_running)
    config = embedded_config(tmp_path, monkeypatch)
    previous = signal.getsignal(signal.SIGTERM)
    try:
        assert main(["--config", str(config), "serve"]) == SIGTERM_EXIT
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert cleaned == ["finally ran"]


# issue-20: the TUI asserts a participant — --participant, else the OS user name (R1).


def test_tui_parses_a_participant() -> None:
    parser = build_parser()
    assert parser.parse_args(["tui", "--participant", "alice"]).participant == "alice"
    assert parser.parse_args(["tui"]).participant is None


def test_tui_participant_is_the_flag_else_the_os_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: "osuser")
    parser = build_parser()
    assert tui_participant(parser.parse_args(["tui", "--participant", " alice "])) == "alice"
    assert tui_participant(parser.parse_args(["tui"])) == "osuser"


def test_tui_participant_is_none_when_nothing_can_be_asserted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_user() -> str:
        raise OSError("No username set in the environment")

    monkeypatch.setattr(getpass, "getuser", no_user)
    parser = build_parser()
    assert tui_participant(parser.parse_args(["tui"])) is None
    assert tui_participant(parser.parse_args(["tui", "--participant", "  "])) is None


@pytest.mark.parametrize("flag", [["--participant", ""], ["--participant", "   "], []])
def test_tui_without_a_participant_exits_two_before_connecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: list[str],
) -> None:
    from tiny_harness.service import commands

    def no_user() -> str:
        raise OSError("No username set in the environment")

    async def must_not_run(*_: object, **__: object) -> int:
        raise AssertionError("the TUI must not start without a participant")

    monkeypatch.setattr(getpass, "getuser", no_user)
    monkeypatch.setattr(commands, "tui", must_not_run)
    config = embedded_config(tmp_path, monkeypatch)
    assert main(["--config", str(config), "tui", *flag]) == CONFIG_EXIT
    assert "--participant" in capsys.readouterr().err


def test_tui_passes_the_resolved_participant_to_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiny_harness.service import commands

    calls: list[tuple[str | None, str]] = []

    async def record(_: object, *, url: str | None, participant: str) -> int:
        calls.append((url, participant))
        return 0

    monkeypatch.setattr(getpass, "getuser", lambda: "osuser")
    monkeypatch.setattr(commands, "tui", record)
    config = embedded_config(tmp_path, monkeypatch)
    assert main(["--config", str(config), "tui", "--url", "http://x"]) == 0
    assert main(["--config", str(config), "tui", "--participant", "alice"]) == 0
    assert calls == [("http://x", "osuser"), (None, "alice")]


async def test_tui_command_hands_the_participant_to_run_tui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiny_harness.config import Settings
    from tiny_harness.interaction import tui as tui_module
    from tiny_harness.service import commands

    calls: list[tuple[str, str]] = []

    async def fake_run_tui(url: str, *, participant: str) -> int:
        calls.append((url, participant))
        return 0

    monkeypatch.setattr(tui_module, "run_tui", fake_run_tui)
    settings = Settings.load(embedded_config(tmp_path, monkeypatch))
    assert await commands.tui(settings, url="http://x", participant="alice") == 0
    assert calls == [("http://x", "alice")]
