---
type: testing-plan
phase: test-planning
workItem: issue-17
status: approved
approvedBy: ["MadaraUchiha-314"]
overrides: {}
---

<!-- Written per the `the-loop:writing` skill: front-load each section's
     conclusion, draw it rather than describe it (3+ named parts -> a mermaid
     diagram), and keep the formal registers formal (EARS, abuse cases,
     RFC-2119, API contracts, schema descriptions). No length limit — length
     follows the change; the test is whether a sentence can come out without
     losing information. A gated section stays even when it is empty. -->

# Testing plan: Support embedded Temporal mode

> Derived from the approved [requirements](requirements.md) and the [design](design.md),
> **before** `tasks.md` — each task's `_Test:_` names a row of the matrix below. Authored
> at the `test-planning` node and **completed at the `verification` node**.
>
> **This file is executable content.** It names commands an agent will run, so review it
> like code. Credentials appear **by reference only**.

The proof runs on three levels. **Unit** tests cover the config rules and the
`EmbeddedTemporal` file, lock and error handling with `start_local` stubbed.
**Integration** tests start the real Temporal dev server with no credentials at all.
They prove loopback binding, shutdown, the state lock, restart durability, and the
programmatic and TUI paths. **One end-to-end** run of the demo in embedded mode proves the
headline: the harness runs with no Temporal account. Remote mode's existing suites run
unchanged as the regression guard.

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | `TemporalConfig` per-mode rules and `load_settings` secret handling (R1); `cli.dispatch` exit codes for `worker` and the admin commands in embedded mode (R5.2, R5.5); `EmbeddedTemporal` with `start_local` stubbed: database and lock creation, `0600`/`0700` modes, private download dir, error wrapping, lock release, log lines (R2.4, R2.5, R3.1, R3.2, R3.4, R4) | `uv run pytest tests/unit` (also the pre-commit hook) |
| T2 | Integration (scenario) | yes | the real dev server through `EmbeddedTemporal` / `temporal_client` / `running_harness`, Gherkin-documented: start without credentials, loopback bind, stop on every exit path, lock, restart durability, the programmatic harness completing a task with a stub model, `tiny-harness tui` hosting its own harness (R2, R3.3, R5.1, R5.3, R6) | `uv run pytest tests/integration/embedded` (in CI's `uv run pytest tests/integration`) |
| T3 | Contract (OpenAPI / GraphQL SDL) | n/a — no API surface changes: the A2A protocol, the agent card and the REST/JSON-RPC shapes are untouched, and the existing `tests/contract` suite runs as regression in T10 | | |
| T4 | End-to-end | yes | the demo with `examples/demo/config.embedded.toml`, started with **no** `TEMPORAL_API_KEY` in the environment, takes one A2A message through a real model to a terminal task state (R6.4, R1.4) | `uv run pytest tests/e2e -k embedded` (marked `e2e`; skips with a reason when `OPENAI_API_KEY` is absent) |
| T5 | UI / visual | n/a — no rendered state changes: the TUI and web renderer are unchanged (design § UI/UX: N/A); the existing `tests/ui` snapshot suite runs as regression in T10, and the TUI-hosting path is proved behaviourally in T2 | | |
| T6 | Snapshot | n/a — no serialized output changes; config error messages are asserted exactly in T1 instead of snapshotted | | |
| T7 | Performance | yes (measurement, not a gate) | NFR startup budget: time from `EmbeddedTemporal.__aenter__` to a connected client with the binary cached, recorded over 5 starts; the budget is ≤ 10 s. A test asserting a wall-clock bound would be flaky on CI, so the number is recorded, and a breach escalates rather than failing the build | `uv run pytest tests/integration/embedded -k startup_time -s` |
| T8 | Security / abuse case | yes | one negative test per row of design § Security design's abuse-case table, including the two design-level cases (temp-dir binary plant, two processes on one database) | `uv run pytest tests/unit tests/integration/embedded tests/security -k embedded` |
| T9 | Accessibility | n/a — no user interface is added or changed | | |
| T10 | Migration / regression | yes | every existing configuration keeps working with no `mode` key (R1.2): `examples/demo/config.toml` loads as remote and still requires `TEMPORAL_API_KEY`; the full existing suite passes unchanged | `uv run pre-commit run --all-files` and `uv run pytest tests/integration tests/contract tests/security tests/ui` (CI's exact commands) |
| T11 | Manual exploratory | yes | the first-run experience on a machine with no Temporal: `tiny-harness tui` in embedded mode, one message sent, then quit; confirm no `temporal` process remains, the database is `0600`, and the WARNING line appears (R5.3, R2.3, R2.5) | procedure under Verification activities |
| T12 | Documentation | yes | README, configuration reference, capability doc and deployment guide describe embedded mode (R7); the docs site builds | `bun run --cwd docs docs:build`; markdownlint via pre-commit |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1.1, R1.2 | absent `mode` → `remote`; `remote`/`embedded` accepted |
| T1 | R1.3 | remote without `address` / `namespace` / `TEMPORAL_API_KEY` → `ConfigError` naming each |
| T1 | R1.4, R1.7 | embedded with no address and no key loads; `namespace` defaults to `default` |
| T1 | R1.5 | embedded + `address` / + `tls` / + `TEMPORAL_API_KEY` → `ConfigError` naming the key; remote + `[temporal.embedded]` → `ConfigError` |
| T1 | R1.6 | `mode = "embeded"` → `ConfigError(temporal.mode)`, reported before the missing-key check |
| T1 | R2.4 | `start_local` raises → `EmbeddedTemporalError` with the cause; lock released; remote `connect` never called |
| T1 | R2.5 | INFO line (mode, address, namespace, database) and WARNING line emitted on start |
| T1 | R3.1, R3.2, R3.4 | default database beside the store; `database_path` honoured; `persist = false` passes no database to `start_local` |
| T1 | R4.1–R4.4 | `binary_path` passed through and no download dir used for it; missing / non-executable path → `ConfigError`; INFO line on download |
| T1 | R5.2, R5.5 | `worker` in embedded → exit 2; `schedules delete` / `tasks purge` with `persist = false` → exit 2 |
| T2 | R1.4, R2.1 | `Scenario: Embedded mode starts without Temporal credentials` |
| T2 | R2.2 | `Scenario: Embedded server binds loopback only` |
| T2 | R2.3 | `Scenario: Embedded server stops when the harness exits` (normal exit, exception, cancellation) |
| T2 | R2.6, R2.7 | `Scenario: Embedded server registers search attributes and the heartbeat schedule` |
| T2 | R3.3 | `Scenario: Embedded state survives a restart` |
| T2 | design § lock | `Scenario: A second process cannot open the same embedded state` |
| T2 | R5.1, R6.1–R6.3 | `Scenario: Programmatic harness runs a task in embedded mode` |
| T2 | R5.3 | `Scenario: TUI hosts its own harness in embedded mode` |
| T2 | R5.4 | `Scenario: TUI with a URL starts no embedded server` |
| T2 | R5.5 | `Scenario: Admin commands act on persisted embedded state` |
| T4 | R6.4, R1.4 | `Scenario: Demo completes a task in embedded mode without Temporal credentials` |
| T7 | NFR startup | median and max of 5 cached starts |
| T8 | abuse cases 1–8, design rows | see design § Security design table; each case is one named test |
| T10 | R1.2 | existing demo config loads unchanged as remote; existing suites green |
| T11 | R5.3, R2.3, R2.5 | manual first-run walkthrough |
| T12 | R7.1–R7.3 | doc sections present; site builds |

## Verification environment

- **Repositories:** this repository only, at the head of the work item's implementation
  branch.
- **Services / containers:** none to start by hand. The Temporal CLI dev server is
  started by the code under test, which is the point. It is downloaded on first use into
  the integration cache `~/.cache/temporalio` (the suite's existing `CACHE`), passed as
  `temporal.embedded.download_dir` so CI and local runs reuse it.
- **Network:** the first T2 run needs outbound HTTPS to Temporal's release host to fetch
  the CLI binary. T4 needs outbound HTTPS to OpenAI.
- **Fixtures & data:** each T2 test uses a `tmp_path` state directory, an OS-chosen port
  and a unique task queue. The stub model is the existing integration `LLMResponse`
  scripting (`tests/integration/durable/conftest.py`).
- **Credentials:** **by reference only.**
  - T1, T2, T7, T8, T10, T11: **none**. `TEMPORAL_API_KEY` MUST be unset for the
    embedded runs (`env -u TEMPORAL_API_KEY …`), which is itself part of the proof.
  - T4: `OPENAI_API_KEY` (keyring: `secret-tool lookup service openai project
    tiny-harness`) and `TINY_HARNESS_PUSH_KEY` (`openssl rand -base64 32`).
  - T11: `OPENAI_API_KEY`, `TINY_HARNESS_PUSH_KEY` as above.
- **Bring-up:** `uv sync --locked` (Python); `bun install --cwd docs --frozen-lockfile`
  (T12 only).
- **Tear-down:** none needed; each test's context manager stops its server. T11 checks
  that explicitly with `pgrep -fa 'temporal server start-dev'`.
- **If bring-up fails** (for example the binary download is blocked): record it under
  Verification results, leave the dependent activities unticked, and escalate on the PR.
  Do not pass the gate on an environment that never came up.

## Evidence plan

All textual evidence is markdown, redacted of `OPENAI_API_KEY`, `TINY_HARNESS_PUSH_KEY`
and the user's home path before commit (the e2e helper's `redact()` already does the
first two).

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1 | pytest summary (counts, duration) and the red→green transitions recorded per task | `unit.md` |
| T2 | `the-loop scenarios --root "$PWD" --glob 'tests/integration/embedded/*.py' --format markdown` table plus the run output | `integration.md` |
| T4 | the e2e run output and the task's terminal state, redacted | `e2e.md` |
| T7 | the five timings, median and max, binary version | `performance.md` |
| T8 | the abuse-case → test → result table | `security-tests.md` |
| T10 | pre-commit and CI-command output summaries | `regression.md` |
| T11 | the procedure, the observed output, an SVG screenshot of the TUI connected to its embedded harness (Textual `save_screenshot`), the `pgrep` and `stat` output | `manual-walkthrough.md`, `ui/tui-embedded.svg` |
| T12 | the docs build summary and the list of docs changed | `documentation.md` |

## Verification activities

- [ ] T1 — `env -u TEMPORAL_API_KEY uv run pytest tests/unit`
- [ ] T2 — `env -u TEMPORAL_API_KEY uv run pytest tests/integration/embedded`, then
  `the-loop scenarios --root "$PWD" --glob 'tests/integration/embedded/*.py' --format markdown`
- [ ] T4 — `env -u TEMPORAL_API_KEY uv run pytest tests/e2e -k embedded` with
  `OPENAI_API_KEY` and `TINY_HARNESS_PUSH_KEY` exported (by reference, above)
- [ ] T7 — `env -u TEMPORAL_API_KEY uv run pytest tests/integration/embedded -k startup_time -s`
- [ ] T8 — `env -u TEMPORAL_API_KEY uv run pytest tests/unit tests/integration/embedded tests/security -k embedded`
- [ ] T10 — `uv run pre-commit run --all-files` and
  `uv run pytest tests/integration tests/contract tests/security tests/ui`
- [ ] T11 — manual: in a shell with `TEMPORAL_API_KEY` unset, run
  `uv run tiny-harness --config examples/demo/config.embedded.toml tui`; confirm the
  INFO and WARNING lines in the log; send one message and see a reply; quit with
  `q` (the TUI's quit binding, outside the input box); run `pgrep -fa 'temporal server start-dev'` (expect nothing) and
  `stat -c '%a %n' examples/demo/.state/temporal.sqlite3*` (expect `600`)
- [ ] T12 — `bun run --cwd docs docs:build`; confirm R7.1–R7.3 sections exist

## Verification results

_Not yet executed._

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| | | | |

**Not executed:** —

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109). Append-only and attributed: an approval never silently
> discards a reviewer's suggestions, and the feedback travels with the document
> it concerns rather than living in a side-channel tracker.

### 2026-10-10 — approved

**@MadaraUchiha-314** wrote:

approved
