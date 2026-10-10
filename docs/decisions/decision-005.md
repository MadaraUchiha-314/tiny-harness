# Decision 005: Embedded mode runs the SDK's Temporal dev server as an owned child process

- **Status:** proposed (accepted when the issue-17 design is approved)
- **Date:** 2026-10-10
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #17](https://github.com/MadaraUchiha-314/tiny-harness/issues/17)

## Context

[Decision 002](decision-002.md) made Temporal a hard dependency of the server, including
for local development. Issue #17 asks that a consumer without a Temporal instance can
still run tiny_harness: an "embedded" mode that starts a local Temporal for the
process, from the same configuration the CLI and the programmatic entry point share.

## Decision

1. **`[temporal] mode = "remote" | "embedded"`, default `remote`.** Embedded mode is an
   explicit opt-in; it forbids `address`, `tls` and `TEMPORAL_API_KEY`.
2. **Embedded mode starts the Temporal CLI dev server through the SDK already in use**
   (`temporalio.testing.WorkflowEnvironment.start_local`), bound to `127.0.0.1`,
   persisted to a `0600` SQLite file beside the store, and stopped when the owning
   process exits. One `temporal_client(settings)` context manager is the only place
   either mode opens a client.
3. **One owner per embedded state**, enforced by a file lock beside the database.
4. **The binary is pinned or downloaded privately**: `temporal.embedded.binary_path`
   disables downloads; otherwise the SDK downloads to a user-private cache directory,
   never the shared system temp directory.

## Consequences

- `tiny-harness serve`, `tiny-harness tui` and the demo run with no Temporal account.
- "In-process" is a child process whose lifetime is the harness's; a SIGKILL can orphan
  it (documented).
- The embedded frontend is unauthenticated on loopback: embedded mode is for
  single-user development hosts and tests, not production (deployment guide).
- Embedded state is not shareable between processes; `worker` as a separate process is
  refused in embedded mode.

## Alternatives considered

- **Embedded when no address is configured** — a production config that loses its
  Temporal section would silently run an unauthenticated local server.
- **Spawning the `temporal` binary ourselves** — buys parent-death signalling, costs
  re-implementing download, readiness and port selection the SDK already does.
- **A shared embedded server other processes can connect to** — makes an
  unauthenticated port a supported interface; a separate, larger feature.
