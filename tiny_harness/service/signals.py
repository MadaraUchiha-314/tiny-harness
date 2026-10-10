"""SIGTERM for an asyncio process that owns an embedded Temporal (issue-17 R2.3).

SIGTERM cancels the main task, exactly as asyncio's own SIGINT handling does, so the
``finally`` blocks that stop the worker and an embedded dev server unwind in order. Two
alternatives fail: a plain handler raising ``KeyboardInterrupt`` makes asyncio cancel every
task at once (the worker's pollers included) and shutdown hangs; and no handler at all lets
uvicorn, which takes SIGTERM over while it serves, restore the default action and re-raise
it after its own shutdown, killing the process before the dev server is stopped.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal


def cancel_on_sigterm() -> asyncio.Event:
    """Cancel the current task on SIGTERM; the returned event says it happened."""
    received = asyncio.Event()
    task = asyncio.current_task()
    if task is None:
        return received

    def on_sigterm() -> None:
        received.set()
        task.cancel()

    with contextlib.suppress(NotImplementedError, RuntimeError):  # Windows; non-main thread
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, on_sigterm)
    return received


__all__ = ["cancel_on_sigterm"]
