# Learning 006: SIGTERM in an asyncio process must cancel the main task, not raise

- **Date:** 2026-10-10
- **Source:** system-feedback
- **Work item:** issue-17

## What happened

Embedded Temporal runs as a child process that the harness has to stop in a `finally`.
Two obvious SIGTERM strategies both left it running:

- A `signal.signal` handler raising `KeyboardInterrupt` made asyncio cancel every task
  at once, the Temporal worker's pollers included. The worker's shutdown then hung.
- Installing no handler let uvicorn, which takes SIGTERM over while it serves, restore
  the default action and re-raise the signal after its own shutdown. That killed the
  process before the `finally` ran.

Only tests that sent a real SIGTERM to a real subprocess and then looked for the child
caught either case.

## Learning

In an asyncio process, handle SIGTERM with `loop.add_signal_handler(SIGTERM,
main_task.cancel)`, which is what asyncio itself does for SIGINT. Install it in every
entry point that owns a child process, not only in the CLI. Prove it with a subprocess
test that signals and then asserts no child remains.

## Action

`tiny_harness/service/signals.py` (`cancel_on_sigterm`), used by the CLI and by
`service.serve`. `tests/integration/embedded/test_cli_embedded.py` covers both paths.
