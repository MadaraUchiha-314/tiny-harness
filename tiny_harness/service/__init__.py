"""The service layer: durable execution, the A2A server, inbox, heartbeat and the CLI
(R14-R16, R19, R21).

The programmatic entry points (issue-17 R6) — the same code the CLI runs, driven by the
same ``Settings``:

- ``Harness(settings)``: one agent's runtime, started from a host app's lifespan, and
  ``harness.asgi_app()`` to mount on a Starlette or FastAPI app (issue-36);
  ``harnesses_lifespan(*harnesses)`` starts several in one lifespan.
- ``running_harness(settings)``: an async context manager yielding a started harness
  (A2A server, worker, and Temporal per ``temporal.mode``); everything stops on exit.
- ``serve(settings)``: run until the process is asked to stop.
- ``temporal_client(settings)``: just a connected Temporal client, embedded or remote.
- ``complete_message(task_id, participant_id=...)``: the A2A message that asks to
  complete a task (issue-25 R5.1, R11.3).

They are imported on first use, so ``tiny-harness --version`` and a configuration error
do not pay for importing the whole service stack.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tiny_harness.service.a2a.app import RouteOptions
    from tiny_harness.service.durable.temporal import temporal_client
    from tiny_harness.service.harness import Harness, harnesses_lifespan
    from tiny_harness.service.inbox import complete_message
    from tiny_harness.service.process import RunningHarness, running_harness, serve

_EXPORTS = {
    "Harness": "tiny_harness.service.harness",
    "harnesses_lifespan": "tiny_harness.service.harness",
    "RouteOptions": "tiny_harness.service.a2a.app",
    "RunningHarness": "tiny_harness.service.process",
    "running_harness": "tiny_harness.service.process",
    "serve": "tiny_harness.service.process",
    "temporal_client": "tiny_harness.service.durable.temporal",
    "complete_message": "tiny_harness.service.inbox",
}


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(_EXPORTS[name]), name)


__all__ = [
    "Harness",
    "RouteOptions",
    "RunningHarness",
    "complete_message",
    "harnesses_lifespan",
    "running_harness",
    "serve",
    "temporal_client",
]
