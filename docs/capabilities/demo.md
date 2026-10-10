# Capability: demo

> One harness instance on Temporal Cloud with `gpt-6.1-sol`, two MCP servers, a skill
> and both renderers on one task; its e2e tests prove the flow and crash recovery.

## What it is

The definition of done of issue-3, kept runnable: `examples/demo` is an Agent Plugin
(the `orders` and `policy` stdio MCP servers, the `support-agent` skill, a prompt
extension) with a `config.toml`, started by `python -m examples.demo`. The
[getting started](../guide/getting-started) guide is the walkthrough.

## Current behaviour

- `python -m examples.demo [CONFIG]` SHALL start the A2A server with an in-process worker
  on `127.0.0.1:8080` through `tiny_harness.service.serve`, serve the built web renderer
  under `/ui` and print how to start the TUI; both surfaces reach the same instance.
  `CONFIG` defaults to `config.toml` (Temporal Cloud); `config.embedded.toml` runs the
  same demo on an embedded Temporal with no Temporal account.
- WHEN the complaint about order #48213 is sent THEN the agent SHALL load the skill,
  create a plan, call `get_order` and `policy.lookup`, emit an A2UI card with the
  resolution options and a Confirm button, ask the reporter and wait in
  `INPUT_REQUIRED`; on the reply or the card's action it SHALL act with
  `ship_replacement` or `refund` and complete with a two-sentence summary.
- The `orders` server SHALL append every call to `$PLUGIN_DATA/orders-ledger.jsonl` and,
  while `$PLUGIN_DATA/slow-get-order` exists, hold `get_order` open, so a test can kill
  the worker mid-activity.
- `tests/e2e/test_demo.py` SHALL drive the conversation through the A2A client (pressing
  the card's button for the first question) and assert the states, the artifact, the
  ledger (a non-idempotent tool at most once), one `chat` span per `invoke_llm` run,
  cached tokens from turn two and no secret in the trace or log.
- `tests/e2e/test_crash_recovery.py` SHALL run the server and the worker as separate
  processes, kill the worker with `SIGKILL` during `get_order` and again while the task
  waits for input, restart it, and assert from Temporal's history that every
  `invoke_llm` was scheduled once and completed once and that the ledger shows
  `ship_replacement` at most once.
- `tests/e2e/test_demo_embedded.py` SHALL run the demo in embedded mode as one `serve`
  process with no `TEMPORAL_API_KEY` in its environment and assert the task completes,
  the embedded server's start and warning are logged, and no secret is in the trace or log.
- The e2e tests SHALL skip with the missing variable's name when a variable they need is
  absent (`OPENAI_API_KEY` and `TEMPORAL_API_KEY`; `OPENAI_API_KEY` alone for the
  embedded demo); each run uses its own task queue, port and state
  directory, and writes redacted evidence to `TINY_HARNESS_E2E_EVIDENCE` when set.

## Design

[design.md § Testing strategy](../specs/issue-3/design.md#testing-strategy),
[testing-plan.md](../specs/issue-3/testing-plan.md) rows T4 and T12.

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | The demo plugin, configuration and e2e tests (Layer 9) | [spec](../specs/issue-3/), [issue #3](https://github.com/MadaraUchiha-314/tiny-harness/issues/3) |
| issue-17 | `config.embedded.toml`, the optional config path, the embedded-mode e2e | [spec](../specs/issue-17/), [PR #18](https://github.com/MadaraUchiha-314/tiny-harness/pull/18) |
