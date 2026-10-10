"""``tiny-harness`` (R21): ``serve``, ``worker``, ``tui``, ``schedules``, ``tasks``.

Every command loads ``Settings`` first; a missing secret or an unknown key exits with
the variable's name on stderr and status 2 (R21.2, R21.3). Secrets come only from the
environment (``TEMPORAL_API_KEY`` in remote mode, ``OPENAI_API_KEY``,
``TINY_HARNESS_PUSH_KEY``). In embedded Temporal mode (issue-17) a command that cannot work
also exits 2 before anything starts, and a dev server that fails to start exits 1.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from tiny_harness import __version__
from tiny_harness.config import Settings
from tiny_harness.errors import ConfigError, EmbeddedTemporalError

CONFIG_EXIT = 2
EMBEDDED_EXIT = 1
SIGTERM_EXIT = 143


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tiny-harness", description="A tiny agent harness.")
    parser.add_argument("--version", action="version", version=f"tiny-harness {__version__}")
    parser.add_argument(
        "--config", type=Path, default=None, help="TOML configuration file (secrets from env)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the A2A server")
    serve.add_argument("--with-worker", action="store_true", help="also run a worker in-process")
    sub.add_parser("worker", help="run a Temporal worker and ensure the heartbeat schedule")
    tui = sub.add_parser("tui", help="open the terminal renderer")
    tui.add_argument("--url", default=None, help="the server's base URL (default: config)")
    schedules = sub.add_parser("schedules", help="manage the heartbeat schedule")
    schedules_sub = schedules.add_subparsers(dest="schedules_command", required=True)
    schedules_sub.add_parser("delete", help="delete the heartbeat schedule")
    tasks = sub.add_parser("tasks", help="task administration")
    tasks_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    purge = tasks_sub.add_parser(
        "purge", help="delete a task's rows from the store and terminate its workflow"
    )
    purge.add_argument("task_id")
    return parser


def load(config: Path | None) -> Settings:
    return Settings.load(config)


def cancel_on_sigterm() -> None:
    """SIGTERM cancels the main task, exactly as asyncio's own SIGINT handling does, so the
    ``finally`` blocks that stop the worker and an embedded Temporal dev server unwind in
    order (issue-17 R2.3). Raising ``KeyboardInterrupt`` from a plain signal handler instead
    would make asyncio cancel every task at once, the worker's pollers included, and its
    shutdown would hang. uvicorn takes the signal over while ``serve`` runs and re-raises it
    after its own shutdown, which lands here too."""
    task = asyncio.current_task()
    if task is None:
        return
    with contextlib.suppress(NotImplementedError, RuntimeError):  # Windows; non-main thread
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)


def refusal(args: argparse.Namespace, settings: Settings) -> str | None:
    """Why this command cannot run in embedded mode, or ``None`` (issue-17 R5.2, R5.5)."""
    temporal = settings.temporal
    if temporal.mode != "embedded":
        return None
    if args.command == "worker":
        return "in embedded mode the worker runs inside serve"
    if args.command in ("schedules", "tasks") and temporal.database_path(settings.store) is None:
        return (
            "embedded Temporal is in-memory (temporal.embedded.persist = false); "
            "there is no state to act on"
        )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load(args.config)
    except ConfigError as exc:
        print(
            f"configuration error: {exc.message} ({exc.detail.get('variable', '')})",
            file=sys.stderr,
        )
        return CONFIG_EXIT
    reason = refusal(args, settings)
    if reason is not None:
        print(f"configuration error: {reason}", file=sys.stderr)
        return CONFIG_EXIT
    try:
        return asyncio.run(dispatch(args, settings))
    except EmbeddedTemporalError as exc:
        print(f"embedded Temporal failed to start: {exc.message}", file=sys.stderr)
        return EMBEDDED_EXIT
    except KeyboardInterrupt:
        return 130
    except asyncio.CancelledError:  # SIGTERM, via cancel_on_sigterm
        return SIGTERM_EXIT


async def dispatch(args: argparse.Namespace, settings: Settings) -> int:
    from tiny_harness.service import commands

    cancel_on_sigterm()
    if args.command == "serve":
        return await commands.serve(settings, with_worker=bool(args.with_worker))
    if args.command == "worker":
        return await commands.worker(settings)
    if args.command == "tui":
        return await commands.tui(settings, url=args.url)
    if args.command == "schedules":
        return await commands.schedules_delete(settings)
    if args.command == "tasks":
        return await commands.tasks_purge(settings, task_id=str(args.task_id))
    return 1


__all__ = ["CONFIG_EXIT", "EMBEDDED_EXIT", "SIGTERM_EXIT", "build_parser", "main"]
