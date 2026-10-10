"""The CLI's commands (R21): each wires a process from ``Settings``. Temporal is reached
through ``temporal_client``, so every command honours ``temporal.mode`` (issue-17)."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import sys
from collections.abc import Awaitable, Callable
from typing import cast

import httpx
from temporalio.service import RPCError

from tiny_harness.config import Settings
from tiny_harness.harness.persistence import PushTokenCipher, SqliteStore
from tiny_harness.service.a2a import PushSink, StorePushConfigStore
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.temporal import temporal_client
from tiny_harness.service.durable.worker import build_worker, ensure_search_attributes
from tiny_harness.service.heartbeat import delete_heartbeat_schedule, ensure_heartbeat_schedule
from tiny_harness.service.process import observe, running_harness
from tiny_harness.service.process import serve as serve_harness
from tiny_harness.service.runtime import AGENT_ID, build_runtime, retention_map

TUI_LOG_NAME = "tiny-harness.log"


async def serve(settings: Settings, *, with_worker: bool = False) -> int:
    return await serve_harness(settings, with_worker=with_worker)


async def worker(settings: Settings) -> int:
    observe(settings)
    async with temporal_client(settings) as client:
        runtime = await build_runtime(settings)
        push_store = StorePushConfigStore(runtime.store, PushTokenCipher(settings.push_key))
        activities = Activities(
            runtime.engine,
            sink=PushSink(push_store, httpx.AsyncClient(timeout=10)),
            client=client,
            retention=retention_map(settings),
        )
        await ensure_search_attributes(client)
        await ensure_heartbeat_schedule(
            client, interval=settings.heartbeat.interval, task_queue=settings.temporal.task_queue
        )
        print(f"worker {AGENT_ID} on {settings.temporal.task_queue}", file=sys.stderr)
        async with build_worker(client, activities, task_queue=settings.temporal.task_queue):
            await asyncio.Event().wait()
    return 0


async def tui(settings: Settings, *, url: str | None) -> int:
    try:
        module = importlib.import_module("tiny_harness.interaction.tui")
    except ImportError:
        print("the TUI renderer is not installed in this build (Layer 7)", file=sys.stderr)
        return 1
    run_tui = cast(Callable[[str], Awaitable[int]], module.run_tui)
    if url is not None or settings.temporal.mode == "remote":
        return await run_tui(url or str(settings.server.base_url))
    # Embedded mode, no URL: host the harness in this process (issue-17 R5.3). Its logs go
    # to a file so they never draw over the terminal the TUI owns.
    log_path = settings.store.sqlite_path.resolve().parent / TUI_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"tiny-harness: embedded harness, logs in {log_path}", file=sys.stderr)
    with log_path.open("a", encoding="utf-8") as log_file:
        observe(settings, stream=log_file)
        async with running_harness(settings) as harness:
            return await run_tui(harness.base_url)


async def schedules_delete(settings: Settings) -> int:
    async with temporal_client(settings) as client:
        try:
            await delete_heartbeat_schedule(client)
        except RPCError as exc:
            print(f"no heartbeat schedule to delete: {exc.message}", file=sys.stderr)
            return 1
    return 0


async def tasks_purge(settings: Settings, *, task_id: str) -> int:
    """Delete the task's rows and terminate its workflow (the deletion request path)."""
    async with temporal_client(settings) as client:
        store = SqliteStore(settings.store.sqlite_path)
        deleted = await store.purge_task(task_id)
        with contextlib.suppress(RPCError):
            await client.get_workflow_handle(task_id).terminate(reason="purged by operator")
    print("purged " + ", ".join(f"{k.value}={v}" for k, v in deleted.items() if v), file=sys.stderr)
    return 0


__all__ = ["schedules_delete", "serve", "tasks_purge", "tui", "worker"]
