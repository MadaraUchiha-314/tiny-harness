"""``TemporalPool`` (issue-36 R5.2, NFR startup): one Temporal connection per connection key
per process, reference-counted.

Several harnesses with the same connection settings share one client, and in embedded mode
one dev server: the first ``acquire`` connects (or starts the server), the last release
closes it. The key of a remote connection holds a SHA-256 of the API key, never the key.
An in-memory embedded server is never shared: each acquire gets its own.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import threading
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import TextIO

from temporalio.client import Client

from tiny_harness.config import Settings

Connector = Callable[[Settings, TextIO | None], AbstractAsyncContextManager[Client]]
PoolKey = tuple[str, ...]

_private = itertools.count()


def pool_key(settings: Settings) -> PoolKey:
    """What makes two settings the same connection. No secret value is part of it."""
    temporal = settings.temporal
    if temporal.mode == "embedded":
        database = temporal.database_path(settings.store)
        if database is None:  # in memory: nothing to share
            return ("embedded-memory", str(next(_private)))
        # The namespace too: a client serves one namespace, and the claims registry keys
        # queues by the namespace it is told (issue-36 self-review 1, #2).
        return ("embedded", str(database), temporal.effective_namespace)
    api_key = temporal.api_key.get_secret_value() if temporal.api_key is not None else ""
    digest = hashlib.sha256(api_key.encode()).hexdigest() if api_key else ""
    return (
        "remote",
        temporal.address or "",
        temporal.effective_namespace,
        str(temporal.tls),
        digest,
    )


@dataclass
class _Entry:
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    users: int = 1
    client: Client | None = None
    error: BaseException | None = None
    stack: AsyncExitStack = field(default_factory=AsyncExitStack)


class TemporalPool:
    """Shared, reference-counted Temporal clients."""

    def __init__(self, connector: Connector | None = None) -> None:
        self._connector = connector or _direct
        self._lock = threading.Lock()
        self._entries: dict[PoolKey, _Entry] = {}

    def open_connections(self) -> int:
        with self._lock:
            return sum(1 for e in self._entries.values() if e.client is not None)

    @asynccontextmanager
    async def client(
        self, settings: Settings, *, output: TextIO | None = None
    ) -> AsyncGenerator[Client]:
        key = pool_key(settings)
        entry = await self._acquire(key, settings, output)
        try:
            assert entry.client is not None
            yield entry.client
        finally:
            await self._release(key, entry)

    async def _acquire(self, key: PoolKey, settings: Settings, output: TextIO | None) -> _Entry:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.users += 1
                first = False
            else:
                entry = self._entries[key] = _Entry()
                first = True
        if first:
            try:
                entry.client = await entry.stack.enter_async_context(
                    self._connector(settings, output)
                )
            except BaseException as exc:
                entry.error = exc
                with self._lock:
                    self._entries.pop(key, None)
                raise
            finally:
                entry.ready.set()
        else:
            try:
                await entry.ready.wait()
            except BaseException:  # cancelled while waiting: give back our share
                await self._release(key, entry)
                raise
            if entry.error is not None:
                # Not the first caller's own exception: it may be that caller's cancellation.
                raise RuntimeError("the shared Temporal connection did not open") from entry.error
        return entry

    async def _release(self, key: PoolKey, entry: _Entry) -> None:
        with self._lock:
            entry.users -= 1
            last = entry.users == 0
            if last and self._entries.get(key) is entry:
                del self._entries[key]
        if last:
            await entry.stack.aclose()


@asynccontextmanager
async def _direct(settings: Settings, output: TextIO | None) -> AsyncGenerator[Client]:
    from tiny_harness.service.durable.temporal import open_client

    async with open_client(settings, output=output) as client:
        yield client


PROCESS_POOL = TemporalPool()
"""The process's one pool; ``temporal_client`` and every ``Harness`` acquire through it."""


__all__ = ["PROCESS_POOL", "Connector", "PoolKey", "TemporalPool", "pool_key"]
