---
type: evidence
workItem: issue-17
---

# Final validation: Support embedded Temporal mode

Summarised from [testing-plan.md § Verification results](../testing-plan.md#verification-results)
and the review records, at the head of PR #18. Embedded runs had `TEMPORAL_API_KEY` unset.

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| R1.1–R1.7 `temporal.mode`: remote by default and unchanged, embedded needs no address or key and refuses `address`/`tls`/`TEMPORAL_API_KEY`, a typo is refused, namespace defaults | unit tests per row of the per-mode table, including `Settings` built in code; the remote demo config still loads as remote and still needs the key | [unit.md](unit.md), [regression.md](regression.md) |
| R2.1–R2.5 start, loopback only, stop on every exit path, no fallback, logged | real dev server: loopback-only on every listening port, stopped after normal/exception/cancellation and SIGTERM (CLI and programmatic `serve`), no fallback on failure, INFO and WARNING lines | [integration.md](integration.md), [security-tests.md](security-tests.md) |
| R2.6–R2.7 search attributes and heartbeat schedule on the embedded server | *Embedded server registers search attributes and the heartbeat schedule* | [integration.md](integration.md) |
| R3.1–R3.4 persistence beside the store, configurable, survives a restart, in-memory opt-in | unit tests for paths; *Embedded state survives a restart* (a running workflow resumes and completes); files `0600` | [unit.md](unit.md), [integration.md](integration.md) |
| R4.1–R4.4 pinned binary or private download | unit tests: pinned path used with no download dir, a bad path refused, a download logged, a cache owned by another user or writable by others refused | [unit.md](unit.md) |
| R5.1–R5.5 CLI: `serve` runs the worker, `worker` refused, `tui` hosts the harness, `--url` stays a client, admin commands on persisted state | CLI unit tests (exit codes) and the CLI scenarios; the manual walkthrough of the real TUI (lifecycle, logs, quit, no leftover process) | [integration.md](integration.md), [manual-walkthrough.md](manual-walkthrough.md) |
| R6.1–R6.4 programmatic entry point, same config | *Programmatic harness runs a task in embedded mode*; the e2e demo, one `serve` process with a real model, reached `COMPLETED` with no Temporal key | [integration.md](integration.md), [e2e.md](e2e.md) |
| R7.1–R7.3 documentation | README, getting started, deployment guide ("not a production deployment"), capability docs; docs site builds | [documentation.md](documentation.md) |
| NFR startup ≤ 10 s | 0.11 s per cached start | [performance.md](performance.md) |
| Security considerations, abuse cases 1–8 | each mapped to a passing negative test; security-review skill: no findings | [security-tests.md](security-tests.md), [security-review.md](security-review.md) |

Reviews: [self-review](self-review.md) (2 rounds, 6 findings fixed),
[critic-review](critic-review.md) (`codex/gpt-6.1-sol`, 2 findings fixed). One gap, stated
in the testing plan: the CLI TUI cannot send a message, because it never asserts a
participant. That defect predates this PR, is out of scope, and is raised on PR #18.
