"""``TemporalPool`` (issue-36 R5.2, NFR startup): settings that name one connection share
one client; the last release closes it; the key never holds the API key."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TextIO, cast

import pytest
from pydantic import SecretStr
from temporalio.client import Client

from tiny_harness.config import Settings
from tiny_harness.service.durable.pool import TemporalPool, pool_key

ENV = {"OPENAI_API_KEY": "sk-x"}


def embedded(
    tmp_path: Path, database: str = "", *, agent: str = "a", persist: bool = True
) -> Settings:
    embedded_table = f'database_path = "{tmp_path / database}"' if database else ""
    if not persist:
        embedded_table = "persist = false"
    path = tmp_path / f"{agent}.toml"
    path.write_text(
        f"""
[agent]
id = "{agent}"
[temporal]
mode = "embedded"
[temporal.embedded]
{embedded_table}
[server]
base_url = "http://127.0.0.1:8080"
[store]
sqlite_path = "{tmp_path / agent}.sqlite3"
"""
    )
    return Settings.load(path, env=ENV)


def remote(tmp_path: Path, key: str = "tmprl_secretvalue") -> Settings:
    path = tmp_path / "remote.toml"
    path.write_text(
        """
[temporal]
address = "x.tmprl.cloud:7233"
namespace = "ns"
[server]
base_url = "http://127.0.0.1:8080"
"""
    )
    return Settings.load(path, env={**ENV, "TEMPORAL_API_KEY": key})


class Recorder:
    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def __call__(self, settings: Settings, output: TextIO | None) -> AsyncGenerator[Client]:
        self.opened += 1
        await asyncio.sleep(0)  # a second acquire arrives while the first connects
        try:
            yield cast(Client, object())
        finally:
            self.closed += 1


async def test_one_connection_is_shared_per_key(tmp_path: Path) -> None:
    recorder = Recorder()
    pool = TemporalPool(recorder)
    settings = [embedded(tmp_path, "shared.sqlite3", agent=n) for n in "abcde"]
    async with (
        pool.client(settings[0]) as first,
        pool.client(settings[1]) as second,
    ):
        assert first is second
        assert pool.open_connections() == 1
    assert (recorder.opened, recorder.closed) == (1, 1)
    assert pool.open_connections() == 0


async def test_concurrent_first_acquires_open_one_connection(tmp_path: Path) -> None:
    recorder = Recorder()
    pool = TemporalPool(recorder)
    settings = [embedded(tmp_path, "shared.sqlite3", agent=n) for n in "abcde"]
    seen: list[Client] = []
    release = asyncio.Event()

    async def use(s: Settings) -> None:
        async with pool.client(s) as client:
            seen.append(client)
            await release.wait()

    tasks = [asyncio.create_task(use(s)) for s in settings]
    while len(seen) < 5:
        await asyncio.sleep(0)
    release.set()
    await asyncio.gather(*tasks)
    assert recorder.opened == 1 and recorder.closed == 1
    assert len({id(c) for c in seen}) == 1


async def test_the_connection_stays_until_the_last_release(tmp_path: Path) -> None:
    recorder = Recorder()
    pool = TemporalPool(recorder)
    a, b = (
        embedded(tmp_path, "shared.sqlite3", agent="a"),
        embedded(tmp_path, "shared.sqlite3", agent="b"),
    )
    async with pool.client(a):
        async with pool.client(b):
            pass
        assert recorder.closed == 0
    assert recorder.closed == 1


async def test_different_databases_are_different_connections(tmp_path: Path) -> None:
    recorder = Recorder()
    pool = TemporalPool(recorder)
    a = embedded(tmp_path, "a-temporal.sqlite3", agent="a")
    b = embedded(tmp_path, "b-temporal.sqlite3", agent="b")
    async with pool.client(a), pool.client(b):
        assert pool.open_connections() == 2


async def test_in_memory_servers_are_never_shared(tmp_path: Path) -> None:
    recorder = Recorder()
    pool = TemporalPool(recorder)
    async with (
        pool.client(embedded(tmp_path, agent="a", persist=False)),
        pool.client(embedded(tmp_path, agent="b", persist=False)),
    ):
        assert recorder.opened == 2


async def test_a_failed_connection_is_not_kept(tmp_path: Path) -> None:
    attempts = 0

    @asynccontextmanager
    async def failing(settings: Settings, output: TextIO | None) -> AsyncGenerator[Client]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("unreachable")
        yield cast(Client, object())  # pragma: no cover

    pool = TemporalPool(failing)
    settings = embedded(tmp_path, "s.sqlite3")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            async with pool.client(settings):
                pass
    assert attempts == 2 and pool.open_connections() == 0


def test_the_remote_key_holds_no_api_key(tmp_path: Path) -> None:
    settings = remote(tmp_path)
    key = pool_key(settings)
    assert all("tmprl_secretvalue" not in part for part in key)
    other = settings.model_copy(
        update={"temporal": settings.temporal.model_copy(update={"api_key": SecretStr("other")})}
    )
    assert pool_key(other) != key


async def test_a_waiter_cancelled_before_the_connection_opens_gives_back_its_share(
    tmp_path: Path,
) -> None:
    """Self-review round 1, finding 1: the last real release still closes the connection."""
    opened = asyncio.Event()
    release_connect = asyncio.Event()
    closed: list[bool] = []

    @asynccontextmanager
    async def slow(settings: Settings, output: TextIO | None) -> AsyncGenerator[Client]:
        opened.set()
        await release_connect.wait()
        try:
            yield cast(Client, object())
        finally:
            closed.append(True)

    pool = TemporalPool(slow)
    a = embedded(tmp_path, "shared.sqlite3", agent="a")
    b = embedded(tmp_path, "shared.sqlite3", agent="b")

    async def use(s: Settings) -> None:
        async with pool.client(s):
            pass

    first = asyncio.create_task(use(a))
    await opened.wait()
    waiter = asyncio.create_task(use(b))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release_connect.set()
    await first
    assert closed == [True]
    assert pool.open_connections() == 0


async def test_a_cancelled_first_caller_is_not_the_waiters_cancellation(tmp_path: Path) -> None:
    opened = asyncio.Event()

    @asynccontextmanager
    async def hanging(settings: Settings, output: TextIO | None) -> AsyncGenerator[Client]:
        opened.set()
        await asyncio.Event().wait()
        yield cast(Client, object())  # pragma: no cover

    pool = TemporalPool(hanging)
    a = embedded(tmp_path, "shared.sqlite3", agent="a")
    b = embedded(tmp_path, "shared.sqlite3", agent="b")

    async def use(s: Settings) -> None:
        async with pool.client(s):
            pass

    first = asyncio.create_task(use(a))
    await opened.wait()
    waiter = asyncio.create_task(use(b))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(RuntimeError, match="did not open"):
        await waiter
    assert first.cancelled()


def test_the_embedded_key_names_the_namespace(tmp_path: Path) -> None:
    """Self-review round 1, finding 2: one shared client serves one namespace."""
    a = embedded(tmp_path, "shared.sqlite3", agent="a")
    other = a.model_copy(update={"temporal": a.temporal.model_copy(update={"namespace": "other"})})
    assert pool_key(a) != pool_key(other)


async def test_a_second_namespace_on_one_embedded_database_is_refused(tmp_path: Path) -> None:
    """Self-review round 2, finding 3: named, not a lock error from the dev server."""
    from tiny_harness.errors import ConfigError

    pool = TemporalPool(Recorder())
    a = embedded(tmp_path, "shared.sqlite3", agent="a")
    other = a.model_copy(update={"temporal": a.temporal.model_copy(update={"namespace": "other"})})
    async with pool.client(a):
        with pytest.raises(ConfigError) as caught:
            async with pool.client(other):
                pass
    assert "'other'" in caught.value.message and "'default'" in caught.value.message
    assert pool.open_connections() == 0
