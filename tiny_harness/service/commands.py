"""The CLI's commands (R21): each wires a process from ``Settings``. Temporal is reached
through ``temporal_client``, so every command honours ``temporal.mode`` (issue-17)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib
import os
import sys
from collections.abc import Awaitable, Callable
from typing import cast

import httpx
from temporalio.service import RPCError

from tiny_harness.config import Settings
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore
from tiny_harness.harness.persistence import SqliteStore
from tiny_harness.service.a2a import PushSink, StorePushConfigStore
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.temporal import temporal_client
from tiny_harness.service.durable.worker import build_worker, ensure_search_attributes
from tiny_harness.service.heartbeat import delete_heartbeat_schedule, ensure_heartbeat_schedule
from tiny_harness.service.process import observe, running_harness
from tiny_harness.service.process import serve as serve_harness
from tiny_harness.service.runtime import build_runtime, default_media_root, retention_map

TUI_LOG_NAME = "tiny-harness.log"


async def serve(settings: Settings, *, with_worker: bool = False) -> int:
    return await serve_harness(settings, with_worker=with_worker)


async def worker(settings: Settings) -> int:
    observe(settings)
    async with temporal_client(settings) as client:
        runtime = await build_runtime(settings)
        push_store = StorePushConfigStore(runtime.store)
        runtime.commands.freeze()  # no command is registered once the worker runs
        activities = Activities(
            runtime.engine,
            commands=runtime.commands,
            sink=PushSink(push_store, httpx.AsyncClient(timeout=10)),
            client=client,
            retention=retention_map(settings),
            media_retention=settings.retention.media,
            task_queue=settings.temporal.effective_task_queue,
        )
        await ensure_search_attributes(client)
        await ensure_heartbeat_schedule(
            client,
            interval=settings.heartbeat.interval,
            task_queue=settings.temporal.effective_task_queue,
            agent_id=settings.agent.id,
        )
        print(
            f"worker {settings.agent.id} on {settings.temporal.effective_task_queue}",
            file=sys.stderr,
        )
        async with build_worker(
            client,
            activities,
            task_queue=settings.temporal.effective_task_queue,
            agent_id=settings.agent.id,
        ):
            await asyncio.Event().wait()
    return 0


async def tui(
    settings: Settings, *, url: str | None, participant: str, hold_ms: int | None = None
) -> int:
    try:
        module = importlib.import_module("tiny_harness.interaction.tui")
    except ImportError:
        print("the TUI renderer is not installed in this build (Layer 7)", file=sys.stderr)
        return 1
    run_tui = cast(Callable[..., Awaitable[int]], module.run_tui)
    if hold_ms is not None:  # hold-to-talk's repeat window (issue-38)
        run_tui = functools.partial(run_tui, hold_ms=hold_ms)
    if url is not None or settings.temporal.mode == "remote":
        return await run_tui(url or str(settings.server.base_url), participant=participant)
    # Embedded mode, no URL: host the harness in this process (issue-17 R5.3). Its logs go
    # to a file so they never draw over the terminal the TUI owns.
    log_path = settings.store.sqlite_path.resolve().parent / TUI_LOG_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"tiny-harness: embedded harness, logs in {log_path}", file=sys.stderr)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.chmod(log_path, 0o600)  # owner-only like the state files, also when it already existed
    with os.fdopen(descriptor, "a", encoding="utf-8") as log_file:
        observe(settings, stream=log_file)
        async with running_harness(settings, log_stream=log_file) as harness:
            return await run_tui(harness.base_url, participant=participant)


async def schedules_delete(settings: Settings) -> int:
    async with temporal_client(settings) as client:
        try:
            await delete_heartbeat_schedule(client, settings.agent.id)
        except RPCError as exc:
            print(f"no heartbeat schedule to delete: {exc.message}", file=sys.stderr)
            return 1
    return 0


async def purge_media(settings: Settings, *, task_id: str) -> int:
    """Delete every media object of the task (issue-38); 0 when media is off."""
    if settings.media is None:
        return 0
    store = FileMediaStore(
        EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), default_media_root(settings).resolve()
    )
    return await store.delete_task(task_id)


async def tasks_purge(settings: Settings, *, task_id: str) -> int:
    """Terminate the task's workflow, then delete its rows and media (the deletion
    request path). Terminated first: a running workflow could still write a row or a
    medium (a spoken reply, a generated image) after the delete (self-review 2.4)."""
    async with temporal_client(settings) as client:
        with contextlib.suppress(RPCError):
            await client.get_workflow_handle(task_id).terminate(reason="purged by operator")
        store = SqliteStore(settings.store.sqlite_path)
        deleted = {k.value: v for k, v in (await store.purge_task(task_id)).items()}
        deleted["media"] = await purge_media(settings, task_id=task_id)
    print("purged " + ", ".join(f"{k}={v}" for k, v in deleted.items() if v), file=sys.stderr)
    return 0


__all__ = ["purge_media", "schedules_delete", "serve", "tasks_purge", "tui", "worker"]
