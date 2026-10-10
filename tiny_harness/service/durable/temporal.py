"""The Temporal client for either mode (issue-17): ``temporal_client`` connects to a remote
Temporal, or starts the Temporal CLI dev server for this process and stops it on exit.

Embedded mode's server is a child process owned by the harness: bound to loopback only,
persisted to an owner-only SQLite file guarded by a lock (one owner per state), and run
from a binary that is either pinned by the operator or downloaded into a user-private
cache, never the shared temporary directory the SDK defaults to (design.md § Security
design)."""

from __future__ import annotations

import contextlib
import logging
import os
import stat
import sys
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from pathlib import Path
from types import TracebackType
from typing import TextIO

from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from tiny_harness.config import EmbeddedTemporalConfig, Settings, StoreConfig, TemporalConfig
from tiny_harness.errors import EmbeddedTemporalError
from tiny_harness.service.durable.client import connect

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows: no flock; the lock is skipped with a warning
    fcntl = None

log = logging.getLogger("tiny_harness.temporal")

LOOPBACK = "127.0.0.1"  # not configurable: the embedded frontend has no authentication
CACHED_BINARY_GLOB = "temporal-sdk-python-*"  # the SDK's name for a downloaded CLI
# Module-level so tests can stub the server; the SDK's signature has one unparameterized
# ``SearchAttributeKey`` default, which is all pyright reports here.
start_local = WorkflowEnvironment.start_local  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


def default_download_dir() -> Path:
    """``$XDG_CACHE_HOME/tiny-harness/temporal``, else ``~/.cache/tiny-harness/temporal``."""
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "tiny-harness" / "temporal"


def _private_download_dir(path: Path) -> Path:
    """Create it ``0700``; refuse one other users can write, where a binary could be planted."""
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
        path.chmod(0o700)  # mkdir's mode is masked by the umask
    if stat.S_IMODE(path.stat().st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
        raise EmbeddedTemporalError(
            f"the Temporal download directory {path} is writable by other users; "
            "use a private directory (temporal.embedded.download_dir) or pin "
            "temporal.embedded.binary_path"
        )
    return path


def _owner_only(database: Path) -> None:
    """Tighten the database and SQLite's side files to ``0600``.

    The dev server creates its schema only when the file does not exist, so the file cannot
    be pre-created private; it is tightened before start (when it already exists) and right
    after start, before any workflow has written to it. SQLite creates the ``-wal`` and
    ``-shm`` files later with the main file's mode."""
    for candidate in (
        database,
        database.with_name(database.name + "-wal"),
        database.with_name(database.name + "-shm"),
    ):
        if candidate.exists():
            candidate.chmod(0o600)


@contextlib.contextmanager
def _child_output(stream: TextIO | None) -> Generator[None]:
    """Point fds 1 and 2 at ``stream`` while the dev server is spawned, so the child (which
    inherits them) prints its banner and warnings there for its whole life rather than on
    a terminal a TUI owns. Restored as soon as the spawn returns."""
    if stream is None:
        yield
        return
    sys.stdout.flush()
    sys.stderr.flush()
    stream.flush()
    saved = (os.dup(1), os.dup(2))
    try:
        os.dup2(stream.fileno(), 1)
        os.dup2(stream.fileno(), 2)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(saved[0])
        os.close(saved[1])


class _StateLock:
    """An exclusive, non-blocking ``flock`` beside the database: two dev servers on one
    SQLite file would corrupt it."""

    def __init__(self, database: Path) -> None:
        self.path = database.with_name(database.name + ".lock")
        self._fd: int | None = None

    def acquire(self) -> None:
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.chmod(self.path, 0o600)
        if fcntl is None:  # pragma: no cover - Windows
            log.warning("no file locking on this platform; embedded Temporal state is unguarded")
            self._fd = fd
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise EmbeddedTemporalError(
                f"state {self.path.with_suffix('')} is in use by another tiny-harness process"
            ) from exc
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        if fcntl is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)
        self._fd = None


class EmbeddedTemporal:
    """Owns one dev server: the state lock, ``start_local`` and shutdown (issue-17 R2-R4).

    ``async with EmbeddedTemporal(config, store) as client`` yields a connected client; every
    exit path (normal, exception, cancellation) shuts the server down and releases the lock.
    """

    def __init__(
        self, config: TemporalConfig, store: StoreConfig, *, output: TextIO | None = None
    ) -> None:
        self._config = config
        self._store = store
        self._output = output
        self._environment: WorkflowEnvironment | None = None
        self._lock: _StateLock | None = None

    async def __aenter__(self) -> Client:
        embedded = self._config.embedded or EmbeddedTemporalConfig()
        database = self._config.database_path(self._store)
        if database is not None:
            database.parent.mkdir(parents=True, exist_ok=True)
            self._lock = _StateLock(database)
            self._lock.acquire()
        try:
            if database is not None:
                _owner_only(database)
            download_dir = _private_download_dir(embedded.download_dir or default_download_dir())
            if embedded.binary_path is None and not any(download_dir.glob(CACHED_BINARY_GLOB)):
                log.info("downloading the Temporal CLI dev server to %s", download_dir)
            with _child_output(self._output):
                self._environment = await self._start(embedded, database, download_dir)
            if database is not None:
                _owner_only(database)
        except BaseException:
            self._release()
            raise
        client = self._environment.client
        log.info(
            "embedded Temporal at %s, namespace %s, state %s",
            client.service_client.config.target_host,
            self._config.effective_namespace,
            database if database is not None else "in-memory",
        )
        log.warning(
            "embedded Temporal mode is for development and single-host use, not for production: "
            "the local server has no authentication and no operations tooling"
        )
        return client

    async def _start(
        self, embedded: EmbeddedTemporalConfig, database: Path | None, download_dir: Path
    ) -> WorkflowEnvironment:
        try:
            return await start_local(
                namespace=self._config.effective_namespace,
                data_converter=pydantic_data_converter,
                interceptors=[TracingInterceptor()],
                ip=LOOPBACK,
                port=embedded.port,
                ui=False,
                download_dest_dir=str(download_dir),
                dev_server_existing_path=(
                    str(embedded.binary_path) if embedded.binary_path is not None else None
                ),
                dev_server_database_filename=str(database) if database is not None else None,
                dev_server_log_level="warn",
            )
        except Exception as exc:
            hint = (
                ""
                if embedded.binary_path is not None
                else "; to use an installed Temporal CLI, set temporal.embedded.binary_path"
            )
            raise EmbeddedTemporalError(f"{exc}{hint}") from exc

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if self._environment is not None:
                await self._environment.shutdown()
                log.info("embedded Temporal stopped")
        finally:
            self._environment = None
            self._release()

    def _release(self) -> None:
        if self._lock is not None:
            self._lock.release()
            self._lock = None


@asynccontextmanager
async def temporal_client(
    settings: Settings, *, output: TextIO | None = None
) -> AsyncGenerator[Client]:
    """A connected client for the configured mode; stops what it started on exit (R6.3).
    ``output`` receives an embedded dev server's own stdout and stderr (default: this
    process's)."""
    if settings.temporal.mode == "remote":
        yield await connect(settings.temporal)
        return
    async with EmbeddedTemporal(settings.temporal, settings.store, output=output) as client:
        yield client


__all__ = ["EmbeddedTemporal", "default_download_dir", "temporal_client"]
