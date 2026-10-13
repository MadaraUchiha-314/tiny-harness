"""One harness process from ``Settings`` (R21, issue-17 R5, R6): Temporal per the configured
mode, the runtime, the worker and the A2A server.

``running_harness`` is the programmatic entry point the CLI's ``serve`` and ``tui`` share
with a consumer's own code: it yields once the server is listening and, on exit, stops the
server, the worker and (in embedded mode) the Temporal dev server, in that order.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

import httpx
import uvicorn
from a2a.server.tasks import BasePushNotificationSender
from temporalio.client import Client
from uvicorn.config import LOGGING_CONFIG

from tiny_harness.config import Settings
from tiny_harness.harness.commands import CommandHandler, CommandSpec
from tiny_harness.harness.models import ModelCatalog
from tiny_harness.harness.plugins import Plugin
from tiny_harness.harness.security import Redactor
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a import (
    HarnessExecutor,
    HarnessRequestHandler,
    PollingEventBridge,
    PushReceiver,
    PushSink,
    StorePushConfigStore,
    TemporalTaskStore,
    build_agent_card,
    create_app,
)
from tiny_harness.service.a2a.card import describe
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.temporal import temporal_client
from tiny_harness.service.durable.worker import build_worker, ensure_search_attributes
from tiny_harness.service.heartbeat import ensure_heartbeat_schedule
from tiny_harness.service.runtime import (
    build_runtime,
    retention_map,
    secret_values,
    workflow_config,
)
from tiny_harness.service.signals import cancel_on_sigterm

log = logging.getLogger("tiny_harness.process")

READY_POLL_SECONDS = 0.05


def bind_address(settings: Settings) -> tuple[str, int]:
    host, _, port = settings.server.bind.rpartition(":")
    return host or "127.0.0.1", int(port or "8080")


def observe(settings: Settings, *, stream: TextIO | None = None) -> None:
    """Logging and trace export for one process (R17.1, R17.5)."""
    from tiny_harness.service.o11y import configure_logging, configure_tracing

    level = logging.getLevelNamesMapping().get(settings.o11y.log_level.upper(), logging.INFO)
    configure_logging(
        level=level, redactor=Redactor(secrets=secret_values(settings)), stream=stream
    )
    configure_tracing(settings.o11y, service_name=settings.o11y.service_name)


def uvicorn_log_config(stream: TextIO) -> dict[str, object]:
    """uvicorn's error and access loggers, written to ``stream`` instead of stdio."""
    handler = {"class": "logging.StreamHandler", "stream": stream}
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"stream": handler},
        "loggers": {
            name: {"handlers": ["stream"], "level": "INFO", "propagate": False}
            for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
        },
    }


@dataclass
class RunningHarness:
    """A started harness: where to reach it, and its Temporal client."""

    base_url: str
    client: Client
    settings: Settings
    _server_task: asyncio.Task[None] = field(repr=False)

    async def wait(self) -> None:
        """Until the A2A server stops (SIGINT/SIGTERM, or ``should_exit``)."""
        await asyncio.shield(self._server_task)


async def _until_started(server: uvicorn.Server, task: asyncio.Task[None]) -> None:
    while not server.started:
        if task.done():
            task.result()  # re-raises the server's own failure
            raise RuntimeError("the A2A server stopped before it started listening")
        await asyncio.sleep(READY_POLL_SECONDS)


@asynccontextmanager
async def running_harness(
    settings: Settings,
    *,
    with_worker: bool = True,
    log_stream: TextIO | None = None,
    plugins: Sequence[Plugin | Path] = (),
    commands: Iterable[tuple[CommandSpec, CommandHandler]] = (),
    builtin_commands: bool = True,
) -> AsyncGenerator[RunningHarness]:
    """Start Temporal (per ``temporal.mode``), the runtime, the worker and the A2A server;
    yield once the server is listening; stop all of them on exit (issue-17 R6.1, R6.2).

    In embedded mode the worker always runs here: no other process can reach the embedded
    server (R5.1). ``log_stream``, when given, receives uvicorn's logs and an embedded dev
    server's output instead of this process's stdout and stderr (the TUI hosting its own
    harness owns the terminal).

    ``plugins``, ``commands`` and ``builtin_commands`` go to ``build_runtime``: an SDK
    caller adds plugins and slash commands in code, or builds without the built-in
    commands (issue-25 R6.8, R11). Nothing here reads or creates ``~/.tiny-harness``
    (R11.2); that is the CLI's choice, through ``tiny_harness.home``."""
    if settings.temporal.mode == "embedded" and not with_worker:
        log.info("embedded mode: the worker runs in this process")
        with_worker = True
    async with (
        temporal_client(settings, output=log_stream) as client,
        contextlib.AsyncExitStack() as stack,
    ):
        runtime = await build_runtime(
            settings, plugins=plugins, commands=commands, builtin_commands=builtin_commands
        )
        push_store = StorePushConfigStore(runtime.store)
        push_http = httpx.AsyncClient(timeout=10)
        stack.push_async_callback(push_http.aclose)
        bridge = PollingEventBridge(client, interval=settings.server.bridge_interval)
        runtime.commands.freeze()  # no command is registered once the card is built
        await runtime.commands.publish(runtime.registry)
        card = build_agent_card(
            describe(settings.card), str(settings.server.base_url), commands=runtime.commands.specs
        )
        executor = HarnessExecutor(
            client,
            task_queue=settings.temporal.task_queue,
            bridge=bridge,
            config=workflow_config(settings),
            redactor=runtime.redactor,
            delegators=settings.server.delegators,
            models=ModelCatalog.from_settings(settings).selectable,
        )
        activities = Activities(
            runtime.engine,
            commands=runtime.commands,
            sink=PushSink(push_store, push_http),
            client=client,
            retention=retention_map(settings),
            push_base_url=str(settings.server.base_url),
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

        app = create_app(
            handler, card, config=settings.server, monitor=monitor, push=PushReceiver(client)
        )
        if with_worker:
            await ensure_search_attributes(client)
            await ensure_heartbeat_schedule(
                client,
                interval=settings.heartbeat.interval,
                task_queue=settings.temporal.task_queue,
            )
            await stack.enter_async_context(
                build_worker(client, activities, task_queue=settings.temporal.task_queue)
            )
        host, port = bind_address(settings)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="info",
                log_config=uvicorn_log_config(log_stream) if log_stream else LOGGING_CONFIG,
            )
        )
        task = asyncio.create_task(server.serve())
        try:
            await _until_started(server, task)
            yield RunningHarness(str(settings.server.base_url), client, settings, task)
        finally:
            server.should_exit = True
            await asyncio.wait([task])
            if not task.cancelled() and (error := task.exception()) is not None:
                log.error("the A2A server failed: %s", error)


async def serve(settings: Settings, *, with_worker: bool = False) -> int:
    """Run the harness until the process is asked to stop (R21; issue-17 R6.1). SIGTERM
    stops it in order, embedded Temporal included, and returns 0."""
    observe(settings)
    terminated = cancel_on_sigterm()
    try:
        async with running_harness(settings, with_worker=with_worker) as harness:
            await harness.wait()
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if not terminated.is_set() or task is None:
            raise
        task.uncancel()  # the cancellation was our own SIGTERM handling; absorb it
    return 0


__all__ = ["RunningHarness", "bind_address", "observe", "running_harness", "serve"]
