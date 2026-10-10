"""Feature: Embedded Temporal mode
Requirement: docs/specs/issue-17/requirements.md#R2

The real Temporal CLI dev server, started and stopped by ``EmbeddedTemporal`` with no
Temporal credentials anywhere in the process.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import stat
import statistics
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from temporalio import workflow
from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from tests.integration.durable.conftest import CACHE
from tiny_harness.config import EmbeddedTemporalConfig, StoreConfig, TemporalConfig
from tiny_harness.errors import EmbeddedTemporalError
from tiny_harness.service.durable.temporal import EmbeddedTemporal

REPO = Path(__file__).resolve().parents[3]


@workflow.defn(sandboxed=False)
class WaitForRelease:
    """Runs until signalled: a stand-in for a task workflow mid-conversation."""

    def __init__(self) -> None:
        self.released = False

    @workflow.signal
    def release(self) -> None:
        self.released = True

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self.released)
        return "released"


def embedded(tmp_path: Path, *, persist: bool = True) -> tuple[TemporalConfig, StoreConfig]:
    CACHE.mkdir(parents=True, exist_ok=True)
    temporal = TemporalConfig(
        mode="embedded",
        embedded=EmbeddedTemporalConfig(persist=persist, download_dir=CACHE),
    )
    return temporal, StoreConfig(sqlite_path=tmp_path / "state" / "tiny-harness.sqlite3")


def port_of(client: Client) -> int:
    return int(client.service_client.config.target_host.rpartition(":")[2])


def accepts(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


def non_loopback_address() -> str | None:
    """This host's address on its default route, if it has one."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("192.0.2.1", 9))  # TEST-NET-1: no packet is sent for UDP connect
        except OSError:
            return None
        address = str(sock.getsockname()[0])
    return None if address.startswith("127.") else address


def dev_servers(port: int) -> list[str]:
    """Command lines of running dev servers on ``port`` (Linux ``/proc``)."""
    found: list[str] = []
    for entry in Path("/proc").glob("[0-9]*/cmdline"):
        with contextlib.suppress(OSError):
            argv = entry.read_bytes().split(b"\0")
            line = " ".join(part.decode(errors="replace") for part in argv)
            if "start-dev" in line and f"--port {port}" in line:
                found.append(line)
    return found


def assert_stopped(port: int) -> None:
    assert not accepts("127.0.0.1", port)
    if Path("/proc").exists():
        assert dev_servers(port) == []


@pytest.fixture(autouse=True)
def no_temporal_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)


async def test_embedded_mode_starts_without_temporal_credentials(tmp_path: Path) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R1

    Scenario: Embedded mode starts without Temporal credentials
        Given a configuration with mode embedded and no address
        And no TEMPORAL_API_KEY in the environment
        When the embedded server starts
        Then a connected client reaches the default namespace
    """
    temporal, store = embedded(tmp_path)
    async with EmbeddedTemporal(temporal, store) as client:
        assert client.namespace == "default"
        assert "TEMPORAL_API_KEY" not in os.environ
        await client.workflow_service.get_system_info(GetSystemInfoRequest())


async def test_embedded_server_binds_loopback_only(tmp_path: Path) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R2

    Scenario: Embedded server binds loopback only
        Given the embedded server is running
        When a peer connects to its port on loopback
        Then the connection is accepted
        When a peer connects to the same port on the host's network address
        Then the connection is refused
    """
    temporal, store = embedded(tmp_path, persist=False)
    async with EmbeddedTemporal(temporal, store) as client:
        port = port_of(client)
        assert client.service_client.config.target_host == f"127.0.0.1:{port}"
        assert accepts("127.0.0.1", port)
        address = non_loopback_address()
        if address is not None:
            assert not accepts(address, port)


@pytest.mark.parametrize("exit_path", ["normal", "exception", "cancellation"])
async def test_embedded_server_stops_when_the_harness_exits(tmp_path: Path, exit_path: str) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R2

    Scenario: Embedded server stops when the harness exits
        Given the embedded server is running
        When its owner exits normally, by an exception, or by cancellation
        Then nothing listens on its port
        And no dev server process remains
    """
    temporal, store = embedded(tmp_path, persist=False)
    entered = asyncio.Event()
    ports: list[int] = []

    async def owner() -> None:
        async with EmbeddedTemporal(temporal, store) as client:
            ports.append(port_of(client))
            entered.set()
            if exit_path == "exception":
                raise RuntimeError("boom")
            if exit_path == "cancellation":
                await asyncio.Event().wait()

    task = asyncio.create_task(owner())
    await entered.wait()
    if exit_path == "cancellation":
        task.cancel()
    with contextlib.suppress(RuntimeError, asyncio.CancelledError):
        await task
    assert_stopped(ports[0])


async def test_embedded_state_survives_a_restart(tmp_path: Path) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R3

    Scenario: Embedded state survives a restart
        Given a workflow running on a persisted embedded server
        When the server is stopped and started again on the same database
        Then the workflow is still running
        And a worker on the restarted server completes it
    """
    temporal, store = embedded(tmp_path)
    workflow_id = f"wait-{uuid.uuid4().hex[:8]}"
    queue = f"embedded-{uuid.uuid4().hex[:8]}"
    async with EmbeddedTemporal(temporal, store) as client:
        await client.start_workflow(WaitForRelease.run, id=workflow_id, task_queue=queue)
    async with EmbeddedTemporal(temporal, store) as client:
        handle = client.get_workflow_handle(workflow_id)
        assert (await handle.describe()).status == WorkflowExecutionStatus.RUNNING
        async with Worker(
            client,
            task_queue=queue,
            workflows=[WaitForRelease],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await handle.signal(WaitForRelease.release)
            assert await asyncio.wait_for(handle.result(), timeout=30) == "released"
        state = list((tmp_path / "state").glob("temporal.sqlite3*"))
        assert state and all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in state), [
            (p.name, oct(p.stat().st_mode)) for p in state
        ]


async def test_a_second_process_cannot_open_the_same_embedded_state(tmp_path: Path) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/design.md#security-design

    Scenario: A second process cannot open the same embedded state
        Given a persisted embedded server owned by this process
        When another process starts an embedded server on the same database
        Then the other process fails with "in use by another tiny-harness process"
        And this process's server keeps serving
    """
    temporal, store = embedded(tmp_path)
    script = (
        "import asyncio, sys\n"
        "from pathlib import Path\n"
        "from tiny_harness.config import EmbeddedTemporalConfig, StoreConfig, TemporalConfig\n"
        "from tiny_harness.errors import EmbeddedTemporalError\n"
        "from tiny_harness.service.durable.temporal import EmbeddedTemporal\n"
        "async def main():\n"
        "    t = TemporalConfig(mode='embedded', embedded=EmbeddedTemporalConfig("
        f"download_dir=Path({str(CACHE)!r})))\n"
        f"    s = StoreConfig(sqlite_path=Path({str(store.sqlite_path)!r}))\n"
        "    try:\n"
        "        async with EmbeddedTemporal(t, s):\n"
        "            return 0\n"
        "    except EmbeddedTemporalError as exc:\n"
        "        print(exc.message)\n"
        "        return 3\n"
        "sys.exit(asyncio.run(main()))\n"
    )
    async with EmbeddedTemporal(temporal, store) as client:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=REPO,
            timeout=60,
        )
        assert result.returncode == 3, result.stderr
        assert "in use by another tiny-harness process" in result.stdout
        assert accepts("127.0.0.1", port_of(client))


async def test_an_in_process_second_owner_is_refused_too(tmp_path: Path) -> None:
    temporal, store = embedded(tmp_path)
    async with EmbeddedTemporal(temporal, store):
        with pytest.raises(EmbeddedTemporalError):
            async with EmbeddedTemporal(temporal, store):
                pass


async def test_startup_time(tmp_path: Path) -> None:
    """NFR startup budget (testing-plan T7): recorded, not asserted, so CI never flakes."""
    temporal, store = embedded(tmp_path, persist=False)
    async with EmbeddedTemporal(temporal, store):  # warm the binary cache
        pass
    timings: list[float] = []
    for _ in range(5):
        started = time.monotonic()
        async with EmbeddedTemporal(temporal, store):
            timings.append(time.monotonic() - started)
    print(
        f"\nembedded startup (s): {[round(t, 2) for t in timings]} "
        f"median={statistics.median(timings):.2f} max={max(timings):.2f} budget=10"
    )
    assert timings and timedelta(seconds=max(timings)) > timedelta(0)
