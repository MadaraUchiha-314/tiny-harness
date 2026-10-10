"""``EmbeddedTemporal`` with ``start_local`` stubbed (issue-17 R2.4, R2.5, R3, R4; abuse cases
4, 5, 7, 8 and the design's temp-dir binary plant). The real dev server is the integration
suite's (``tests/integration/embedded``)."""

from __future__ import annotations

import logging
import stat
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from tiny_harness.config import EmbeddedTemporalConfig, StoreConfig, TemporalConfig
from tiny_harness.errors import EmbeddedTemporalError
from tiny_harness.service.durable import temporal as module
from tiny_harness.service.durable.temporal import EmbeddedTemporal, default_download_dir


@dataclass
class FakeEnvironment:
    client: object
    shut_down: bool = False

    async def shutdown(self) -> None:
        self.shut_down = True


@dataclass
class StartLocal:
    """Records the keyword arguments; raises ``error`` when set."""

    error: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=lambda: list[dict[str, object]]())
    environments: list[FakeEnvironment] = field(default_factory=lambda: list[FakeEnvironment]())

    async def __call__(self, **kwargs: object) -> FakeEnvironment:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        database = kwargs.get("dev_server_database_filename")
        if isinstance(database, str) and not Path(database).exists():
            Path(database).write_bytes(b"")  # the server creates it with the umask's mode
            Path(database).chmod(0o644)
        config = SimpleNamespace(target_host="127.0.0.1:40123")
        environment = FakeEnvironment(
            SimpleNamespace(service_client=SimpleNamespace(config=config))
        )
        self.environments.append(environment)
        return environment


@pytest.fixture
def start_local(monkeypatch: pytest.MonkeyPatch) -> StartLocal:
    stub = StartLocal()
    monkeypatch.setattr(module, "start_local", stub)
    return stub


def config(tmp_path: Path, **embedded: object) -> tuple[TemporalConfig, StoreConfig]:
    embedded.setdefault("download_dir", tmp_path / "cache")
    temporal = TemporalConfig(
        mode="embedded", embedded=EmbeddedTemporalConfig.model_validate(embedded)
    )
    return temporal, StoreConfig(sqlite_path=tmp_path / "state" / "tiny-harness.sqlite3")


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def test_starts_on_loopback_with_the_persisted_database(
    tmp_path: Path, start_local: StartLocal
) -> None:
    temporal, store = config(tmp_path)
    async with EmbeddedTemporal(temporal, store) as client:
        assert client is start_local.environments[0].client
    call = start_local.calls[0]
    database = tmp_path / "state" / "temporal.sqlite3"
    assert call["ip"] == "127.0.0.1"
    assert call["ui"] is False
    assert call["namespace"] == "default"
    assert call["dev_server_database_filename"] == str(database.resolve())
    assert call["dev_server_existing_path"] is None
    assert call["download_dest_dir"] == str(tmp_path / "cache")
    assert start_local.environments[0].shut_down


async def test_in_memory_passes_no_database_and_takes_no_lock(
    tmp_path: Path, start_local: StartLocal
) -> None:
    temporal, store = config(tmp_path, persist=False)
    async with EmbeddedTemporal(temporal, store):
        pass
    assert start_local.calls[0]["dev_server_database_filename"] is None
    assert not (tmp_path / "state").exists()


async def test_binary_path_is_passed_through(tmp_path: Path, start_local: StartLocal) -> None:
    binary = tmp_path / "temporal"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    temporal, store = config(tmp_path, binary_path=binary)
    async with EmbeddedTemporal(temporal, store):
        pass
    assert start_local.calls[0]["dev_server_existing_path"] == str(binary)


# Abuse case 7 — the database and its lock are private, new or pre-existing.


async def test_a_new_database_is_owner_only(tmp_path: Path, start_local: StartLocal) -> None:
    temporal, store = config(tmp_path)
    database = tmp_path / "state" / "temporal.sqlite3"
    async with EmbeddedTemporal(temporal, store):
        assert mode(database) == 0o600
        assert mode(database.with_name("temporal.sqlite3.lock")) == 0o600


async def test_database_and_lock_are_owner_only(tmp_path: Path, start_local: StartLocal) -> None:
    temporal, store = config(tmp_path)
    database = tmp_path / "state" / "temporal.sqlite3"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"")
    database.chmod(0o644)
    async with EmbeddedTemporal(temporal, store):
        assert mode(database) == 0o600
        assert mode(database.with_name("temporal.sqlite3.lock")) == 0o600


# Design: the state lock — one owner per database.


async def test_a_second_owner_of_the_same_state_is_refused(
    tmp_path: Path, start_local: StartLocal
) -> None:
    temporal, store = config(tmp_path)
    async with EmbeddedTemporal(temporal, store):
        with pytest.raises(EmbeddedTemporalError, match="in use by another"):
            async with EmbeddedTemporal(temporal, store):
                pass
    assert len(start_local.calls) == 1
    async with EmbeddedTemporal(temporal, store):  # released on exit
        pass


# R2.4, abuse case 5 — a failed start is an error, releases the lock, never falls back.


async def test_start_failure_is_wrapped_and_releases_the_lock(
    tmp_path: Path, start_local: StartLocal, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_remote(*_: object) -> None:
        raise AssertionError("embedded mode must never connect to a remote Temporal")

    monkeypatch.setattr(module, "connect", no_remote)
    start_local.error = RuntimeError("port 7233 already in use")
    temporal, store = config(tmp_path)
    with pytest.raises(EmbeddedTemporalError) as info:
        async with EmbeddedTemporal(temporal, store):
            pass
    assert "port 7233 already in use" in info.value.message
    assert "temporal.embedded.binary_path" in info.value.message
    start_local.error = None
    async with EmbeddedTemporal(temporal, store):  # the lock was released
        pass


# R2.5, abuse case 8; R4.4 — the start is visible in the log.


async def test_logs_the_start_the_warning_and_the_download(
    tmp_path: Path, start_local: StartLocal, caplog: pytest.LogCaptureFixture
) -> None:
    temporal, store = config(tmp_path)
    with caplog.at_level(logging.INFO, logger="tiny_harness.temporal"):
        async with EmbeddedTemporal(temporal, store):
            pass
    messages = [(r.levelno, r.getMessage()) for r in caplog.records]
    infos = [m for level, m in messages if level == logging.INFO]
    warnings = [m for level, m in messages if level == logging.WARNING]
    assert any("downloading" in m and str(tmp_path / "cache") in m for m in infos)
    assert any("127.0.0.1:40123" in m and "temporal.sqlite3" in m and "default" in m for m in infos)
    assert any("not for production" in m for m in warnings)


async def test_no_download_notice_when_the_binary_is_cached(
    tmp_path: Path, start_local: StartLocal, caplog: pytest.LogCaptureFixture
) -> None:
    temporal, store = config(tmp_path)
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    (cache / "temporal-sdk-python-1.34.0").write_text("")
    with caplog.at_level(logging.INFO, logger="tiny_harness.temporal"):
        async with EmbeddedTemporal(temporal, store):
            pass
    assert not any("downloading" in r.getMessage() for r in caplog.records)


# Design: the SDK's default download dir is the shared temp dir; ours is private.


def test_default_download_dir_is_private_and_not_in_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert default_download_dir() == tmp_path / "xdg" / "tiny-harness" / "temporal"
    monkeypatch.delenv("XDG_CACHE_HOME")
    default = default_download_dir()
    assert default == Path.home() / ".cache" / "tiny-harness" / "temporal"
    assert not default.is_relative_to(tempfile.gettempdir())


async def test_download_dir_is_created_owner_only(tmp_path: Path, start_local: StartLocal) -> None:
    temporal, store = config(tmp_path, download_dir=tmp_path / "new" / "cache")
    async with EmbeddedTemporal(temporal, store):
        assert mode(tmp_path / "new" / "cache") == 0o700


async def test_a_download_dir_others_can_write_is_refused(
    tmp_path: Path, start_local: StartLocal
) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    temporal, store = config(tmp_path, download_dir=shared)
    with pytest.raises(EmbeddedTemporalError, match="writable by other users"):
        async with EmbeddedTemporal(temporal, store):
            pass
    assert start_local.calls == []


# The TUI-hosted harness: the dev server's own output goes to the log, not the terminal.


async def test_child_output_goes_to_the_given_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    import os

    async def spawning(**kwargs: object) -> FakeEnvironment:
        os.write(1, b"Temporal Server: localhost:1234\n")  # what the child prints at spawn
        os.write(2, b"level=WARN msg=cluster\n")
        return await StartLocal()(**kwargs)

    monkeypatch.setattr(module, "start_local", spawning)
    temporal, store = config(tmp_path)
    log = tmp_path / "harness.log"
    with log.open("a") as stream:
        async with EmbeddedTemporal(temporal, store, output=stream):
            pass
    os.write(1, b"after\n")
    captured = capfd.readouterr()
    assert "Temporal Server" not in captured.out and "cluster" not in captured.err
    assert "after" in captured.out
    assert "Temporal Server: localhost:1234" in log.read_text()
    assert "level=WARN msg=cluster" in log.read_text()


async def test_a_cached_binary_others_can_write_is_refused(
    tmp_path: Path, start_local: StartLocal
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o700)
    cache.chmod(0o755)  # not writable by others, but the binary inside is
    binary = cache / "temporal-sdk-python-1.34.0"
    binary.write_text("")
    binary.chmod(0o666)
    temporal, store = config(tmp_path)
    with pytest.raises(EmbeddedTemporalError, match="writable by other users"):
        async with EmbeddedTemporal(temporal, store):
            pass
    assert start_local.calls == []


async def test_a_download_dir_owned_by_another_user_is_refused(
    tmp_path: Path, start_local: StartLocal, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    real_getuid = os.getuid
    monkeypatch.setattr(module.os, "getuid", lambda: real_getuid() + 1)
    temporal, store = config(tmp_path)
    (tmp_path / "cache").mkdir(mode=0o700)
    with pytest.raises(EmbeddedTemporalError, match="not owned by this user"):
        async with EmbeddedTemporal(temporal, store):
            pass
    assert start_local.calls == []
