"""The CLI's commands (R21): each wires a process from ``Settings``."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import sys
from collections.abc import Awaitable, Callable
from typing import cast

import httpx
import uvicorn
from a2a.server.tasks import BasePushNotificationSender
from temporalio.service import RPCError

from tiny_harness.config import Settings
from tiny_harness.harness.persistence import PushTokenCipher, SqliteStore
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a import (
    HarnessExecutor,
    HarnessRequestHandler,
    PollingEventBridge,
    PushSink,
    StorePushConfigStore,
    TemporalTaskStore,
    build_agent_card,
    create_app,
)
from tiny_harness.service.a2a.card import AgentDescription
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.client import connect
from tiny_harness.service.durable.worker import build_worker, ensure_search_attributes
from tiny_harness.service.heartbeat import delete_heartbeat_schedule, ensure_heartbeat_schedule
from tiny_harness.service.runtime import AGENT_ID, build_runtime, retention_map, workflow_config


def _bind(settings: Settings) -> tuple[str, int]:
    host, _, port = settings.server.bind.rpartition(":")
    return host or "127.0.0.1", int(port or "8080")


async def serve(settings: Settings, *, with_worker: bool = False) -> int:
    client = await connect(settings.temporal)
    runtime = await build_runtime(settings)
    push_store = StorePushConfigStore(runtime.store, PushTokenCipher(settings.push_key))
    push_http = httpx.AsyncClient(timeout=10)
    bridge = PollingEventBridge(client, interval=settings.server.bridge_interval)
    card = build_agent_card(AgentDescription(), str(settings.server.base_url))
    executor = HarnessExecutor(
        client,
        task_queue=settings.temporal.task_queue,
        bridge=bridge,
        config=workflow_config(settings),
        redactor=runtime.redactor,
    )
    activities = Activities(
        runtime.engine,
        sink=PushSink(push_store, push_http),
        client=client,
        retention=retention_map(settings),
    )
    handler = HarnessRequestHandler(
        bridge=bridge,
        agent_executor=executor,
        task_store=TemporalTaskStore(client, runtime.store),
        agent_card=card,
        push_config_store=push_store,
        push_sender=BasePushNotificationSender(push_http, push_store),
    )

    async def monitor() -> JsonObject:
        snapshot = activities.last_snapshot
        return snapshot.model_dump(mode="json") if snapshot is not None else {"tasks": []}

    app = create_app(handler, card, config=settings.server, monitor=monitor)
    host, port = _bind(settings)
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    if not with_worker:
        await server.serve()
        return 0
    await ensure_search_attributes(client)
    await ensure_heartbeat_schedule(
        client, interval=settings.heartbeat.interval, task_queue=settings.temporal.task_queue
    )
    async with build_worker(client, activities, task_queue=settings.temporal.task_queue):
        await server.serve()
    return 0


async def worker(settings: Settings) -> int:
    client = await connect(settings.temporal)
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
    return await run_tui(url or str(settings.server.base_url))


async def schedules_delete(settings: Settings) -> int:
    client = await connect(settings.temporal)
    try:
        await delete_heartbeat_schedule(client)
    except RPCError as exc:
        print(f"no heartbeat schedule to delete: {exc.message}", file=sys.stderr)
        return 1
    return 0


async def tasks_purge(settings: Settings, *, task_id: str) -> int:
    """Delete the task's rows and terminate its workflow (the deletion request path)."""
    client = await connect(settings.temporal)
    store = SqliteStore(settings.store.sqlite_path)
    deleted = await store.purge_task(task_id)
    with contextlib.suppress(RPCError):
        await client.get_workflow_handle(task_id).terminate(reason="purged by operator")
    print("purged " + ", ".join(f"{k.value}={v}" for k, v in deleted.items() if v), file=sys.stderr)
    return 0


__all__ = ["schedules_delete", "serve", "tasks_purge", "tui", "worker"]
