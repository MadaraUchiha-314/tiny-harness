"""The service layer: durable execution, the A2A server, inbox, heartbeat and the CLI
(R14-R16, R19, R21).

The programmatic entry points (issue-17 R6) — the same code the CLI runs, driven by the
same ``Settings``:

- ``running_harness(settings)``: an async context manager yielding a started harness
  (A2A server, worker, and Temporal per ``temporal.mode``); everything stops on exit.
- ``serve(settings)``: run until the process is asked to stop.
- ``temporal_client(settings)``: just a connected Temporal client, embedded or remote.

They are imported on first use, so ``tiny-harness --version`` and a configuration error
do not pay for importing the whole service stack.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tiny_harness.service.durable.temporal import temporal_client
    from tiny_harness.service.process import RunningHarness, running_harness, serve

_EXPORTS = {
    "RunningHarness": "tiny_harness.service.process",
    "running_harness": "tiny_harness.service.process",
    "serve": "tiny_harness.service.process",
    "temporal_client": "tiny_harness.service.durable.temporal",
}


def __getattr__(name: str) -> object:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(_EXPORTS[name]), name)


__all__ = ["RunningHarness", "running_harness", "serve", "temporal_client"]
