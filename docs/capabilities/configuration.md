# Capability: configuration

> One TOML file validated into typed models that reject unknown keys; every secret from
> the environment only; one CLI that fails to start with the missing variable's name.

## What it is

How a deployment is described and how the processes come up. Lives in
`tiny_harness/config.py`, `tiny_harness/service/cli.py`, `commands.py` and `runtime.py`.

## Current behaviour

- `Settings` SHALL be the sections `temporal`, `openai`, `anthropic` (optional),
  `server`, `heartbeat`, `plugins`, `agents`, `store`, `o11y`, `retries`, `context` and
  `retention`, every model `extra="forbid"`.
- Secrets SHALL come only from `TEMPORAL_API_KEY`, `OPENAI_API_KEY`,
  `TINY_HARNESS_PUSH_KEY` (required) and `ANTHROPIC_API_KEY`, `LANGFUSE_PUBLIC_KEY`,
  `LANGFUSE_SECRET_KEY` (when their features are configured), held as `SecretStr` and
  never printed; the configured values are what the redactor masks.
- WHEN a required secret is missing or a key is unknown THEN the process SHALL exit with
  status 2 and the variable or key on stderr, with no anonymous or local fallback.
- The CLI SHALL be `tiny-harness [--config FILE] serve [--with-worker] | worker | tui
  [--url] | schedules delete | tasks purge <task-id>`; `--version` prints the package
  version.
- `build_runtime` SHALL assemble one process from `Settings`: the built-in plugin, the
  operator's plugins, the MCP tool sources, the skills, the system prompt, the model,
  the store and the in-process engine the activities run over, with the plugin data
  root at `plugin-data/` beside the store.
- The demo configuration SHALL document the keyring lookups
  `secret-tool lookup service temporal project tiny-harness` and
  `secret-tool lookup service openai project tiny-harness`.

## Design

[design.md § Configuration](../specs/issue-3/design.md#configuration-r21--configpy),
[deployment guide](../guide/deployment).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Settings, secrets, errors (Layer 1); the CLI and runtime (Layer 5); `trace_file`, `search_attributes`, `ui_dir`, `cors_origins` (Layers 8–9) | [spec](../specs/issue-3/), [PR #7](https://github.com/MadaraUchiha-314/tiny-harness/pull/7), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11) |
