"""Feature: Embedded Temporal mode
Requirement: docs/specs/issue-17/requirements.md#R5

The CLI's commands in embedded mode: the TUI hosts its own harness, a URL keeps it a pure
client, the admin commands act on the persisted state, and a SIGTERM leaves nothing behind.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from temporalio.client import WorkflowExecutionStatus
from textual.widgets import Input

from tests.integration.durable.conftest import CACHE
from tests.integration.embedded.conftest import ScriptModel, embedded_settings, free_port
from tests.integration.embedded.test_embedded_temporal import WaitForRelease
from tiny_harness.harness.models import scripted
from tiny_harness.interaction import tui as tui_module
from tiny_harness.interaction.tui import HarnessApp, SdkClient
from tiny_harness.service import commands
from tiny_harness.service.durable import temporal as temporal_module
from tiny_harness.service.durable.temporal import EmbeddedTemporal

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def isolated_observability(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """``observe`` installs process-wide logging and the global tracer provider (settable
    once); keep both from leaking into later tests."""
    from tiny_harness.service import o11y

    def no_tracing(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(o11y, "configure_tracing", no_tracing)
    logger = logging.getLogger("tiny_harness")
    saved = (list(logger.handlers), logger.propagate, logger.level)
    yield
    for handler in logger.handlers:
        if handler not in saved[0]:
            logger.removeHandler(handler)
    logger.propagate, logger.level = saved[1], saved[2]


@pytest.mark.usefixtures("isolated_observability")
async def test_tui_hosts_its_own_harness_in_embedded_mode(
    tmp_path: Path,
    script_model: ScriptModel,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R5

    Scenario: TUI hosts its own harness in embedded mode
        Given Settings with mode embedded and no --url
        When tiny-harness tui runs
        Then the TUI connects to a harness started in the same process
        And a message typed in the TUI runs to COMPLETED
        And the harness's logs, uvicorn's logs and the dev server's output go to a file
        And none of them reach the terminal the TUI owns
        When the TUI exits
        Then the harness's A2A server is stopped
    """
    script_model(scripted("Hosted reply."))
    settings = embedded_settings(tmp_path)
    seen: list[str] = []

    async def piloted_tui(url: str) -> int:
        """The real TUI app against the hosted harness, driven by Textual's pilot."""
        seen.append(url)
        client = await SdkClient.connect(url, participant="alice")
        app = HarnessApp(client, url=url, participant="alice")
        try:
            async with app.run_test(size=(110, 36)) as pilot:
                app.query_one("#composer", Input).focus()
                await pilot.press(*"hello", "enter")
                await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
                await pilot.pause()
                assert app.state_name == "COMPLETED", app.state_name
        finally:
            await client.close()
        return 0

    monkeypatch.setattr(tui_module, "run_tui", piloted_tui)
    assert await commands.tui(settings, url=None) == 0
    assert seen == [str(settings.server.base_url)]
    log_file = tmp_path / "state" / commands.TUI_LOG_NAME
    log = log_file.read_text()
    assert stat.S_IMODE(log_file.stat().st_mode) == 0o600
    assert "embedded Temporal at 127.0.0.1:" in log  # the harness's JSON log
    assert "Temporal Server:" in log  # the dev server's own banner
    assert '"POST / HTTP/1.1" 200' in log or "HTTP/1.1" in log  # uvicorn's access log
    captured = capfd.readouterr()
    assert "Temporal Server:" not in captured.out + captured.err
    assert "HTTP/1.1" not in captured.out + captured.err
    host, _, port = settings.server.bind.rpartition(":")
    with socket.socket() as sock:
        assert sock.connect_ex((host, int(port))) != 0


async def test_tui_with_a_url_starts_no_embedded_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R5

    Scenario: TUI with a URL starts no embedded server
        Given Settings with mode embedded
        When tiny-harness tui runs with --url
        Then the TUI connects to that URL
        And no embedded Temporal server is started
    """
    started: list[object] = []

    async def no_start(self: EmbeddedTemporal) -> None:
        started.append(self)
        raise AssertionError("tui --url must not start an embedded server")

    async def fake_tui(url: str) -> int:
        return 0 if url == "http://remote.example:8080" else 1

    monkeypatch.setattr(temporal_module.EmbeddedTemporal, "__aenter__", no_start)
    monkeypatch.setattr(tui_module, "run_tui", fake_tui)
    settings = embedded_settings(tmp_path)
    assert await commands.tui(settings, url="http://remote.example:8080") == 0
    assert started == []


async def test_admin_commands_act_on_persisted_embedded_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R5

    Scenario: Admin commands act on persisted embedded state
        Given a workflow left running in a persisted embedded state
        When tiny-harness tasks purge runs on that workflow's id
        Then the workflow is terminated in the persisted state
    """
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)
    settings = embedded_settings(tmp_path)
    workflow_id = f"purge-{uuid.uuid4().hex[:8]}"
    async with EmbeddedTemporal(settings.temporal, settings.store) as client:
        await client.start_workflow(
            WaitForRelease.run, id=workflow_id, task_queue=f"q-{uuid.uuid4().hex[:6]}"
        )
    assert await commands.tasks_purge(settings, task_id=workflow_id) == 0
    async with EmbeddedTemporal(settings.temporal, settings.store) as client:
        description = await client.get_workflow_handle(workflow_id).describe()
        assert description.status == WorkflowExecutionStatus.TERMINATED


def wait_for_port(port: int, process: subprocess.Popen[str], deadline: float) -> None:
    while time.monotonic() < deadline:
        assert process.poll() is None, process.communicate()[1][-2000:]
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise AssertionError("tiny-harness serve did not start listening")


@pytest.mark.skipif(not Path("/proc").exists(), reason="process listing needs /proc")
async def test_sigterm_to_serve_in_embedded_mode_leaves_no_dev_server(tmp_path: Path) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R2

    Scenario: Embedded server stops when serve receives SIGTERM
        Given tiny-harness serve running in embedded mode
        When the process receives SIGTERM
        Then it exits after stopping the embedded server
        And no Temporal dev server process for its state remains
    """
    port = free_port()
    state = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        "\n".join(
            [
                "[temporal]",
                'mode = "embedded"',
                "[temporal.embedded]",
                f'download_dir = "{CACHE}"',
                "[server]",
                f'bind = "127.0.0.1:{port}"',
                f'base_url = "http://127.0.0.1:{port}"',
                "[store]",
                f'sqlite_path = "{state / "tiny-harness.sqlite3"}"',
                "",
            ]
        )
    )
    env = {k: v for k, v in os.environ.items() if k != "TEMPORAL_API_KEY"}
    env.update(
        OPENAI_API_KEY="sk-unused",
        TINY_HARNESS_PUSH_KEY=base64.b64encode(os.urandom(32)).decode(),
    )
    entry = "from tiny_harness.service.cli import main; raise SystemExit(main())"
    process = subprocess.Popen(
        [sys.executable, "-c", entry, "--config", str(config), "serve"],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        await asyncio.to_thread(wait_for_port, port, process, time.monotonic() + 60)
        assert dev_servers_for(state), "the embedded dev server should be running"
        process.send_signal(signal.SIGTERM)
        _, stderr = await asyncio.to_thread(process.communicate, timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        leftovers = dev_servers_for(state)
        for line in leftovers:  # a SIGKILL orphans the child; never leave one behind
            with contextlib.suppress(ProcessLookupError, ValueError):
                os.kill(int(line.split(" ", 1)[0]), signal.SIGKILL)
    assert "embedded Temporal stopped" in stderr, stderr[-2000:]
    assert dev_servers_for(state) == []


def dev_servers_for(state: Path) -> list[str]:
    """Command lines of running dev servers whose database lives under ``state``."""
    found: list[str] = []
    for entry in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            line = " ".join(p.decode(errors="replace") for p in entry.read_bytes().split(b"\0"))
        except OSError:
            continue
        if "start-dev" in line and str(state) in line:
            found.append(f"{entry.parent.name} {line}")
    return found


@pytest.mark.skipif(not Path("/proc").exists(), reason="process listing needs /proc")
async def test_sigterm_to_programmatic_serve_leaves_no_dev_server(tmp_path: Path) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R6

    Scenario: Embedded server stops when a program running serve receives SIGTERM
        Given a program that calls tiny_harness.service.serve in embedded mode
        When the process receives SIGTERM
        Then it exits 0 after stopping the embedded server
        And no Temporal dev server process for its state remains
    """
    port = free_port()
    state = tmp_path / "state"
    config = tmp_path / "config.toml"
    config.write_text(
        "\n".join(
            [
                "[temporal]",
                'mode = "embedded"',
                "[temporal.embedded]",
                f'download_dir = "{CACHE}"',
                "[server]",
                f'bind = "127.0.0.1:{port}"',
                f'base_url = "http://127.0.0.1:{port}"',
                "[store]",
                f'sqlite_path = "{state / "tiny-harness.sqlite3"}"',
                "",
            ]
        )
    )
    env = {k: v for k, v in os.environ.items() if k != "TEMPORAL_API_KEY"}
    env.update(
        OPENAI_API_KEY="sk-unused",
        TINY_HARNESS_PUSH_KEY=base64.b64encode(os.urandom(32)).decode(),
    )
    program = (
        "import asyncio, sys\n"
        "from pathlib import Path\n"
        "from tiny_harness.config import Settings\n"
        "from tiny_harness.service import serve\n"
        "sys.exit(asyncio.run(serve(Settings.load(Path(sys.argv[1])))))\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(config)],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        await asyncio.to_thread(wait_for_port, port, process, time.monotonic() + 60)
        assert dev_servers_for(state), "the embedded dev server should be running"
        process.send_signal(signal.SIGTERM)
        _, stderr = await asyncio.to_thread(process.communicate, timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
        for line in dev_servers_for(state):
            with contextlib.suppress(ProcessLookupError, ValueError):
                os.kill(int(line.split(" ", 1)[0]), signal.SIGKILL)
    assert dev_servers_for(state) == []
    assert "embedded Temporal stopped" in stderr, stderr[-2000:]
    assert process.returncode == 0, stderr[-2000:]
