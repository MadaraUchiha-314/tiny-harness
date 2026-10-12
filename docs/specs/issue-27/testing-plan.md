---
type: testing-plan
phase: test-planning
workItem: issue-27
status: draft
overrides: {}
---

<!-- Written per the `the-loop:writing` skill: front-load each section's
     conclusion, draw it rather than describe it (3+ named parts -> a mermaid
     diagram), and keep the formal registers formal (EARS, abuse cases,
     RFC-2119, API contracts, schema descriptions). -->

# Testing plan: Remote sub-tasks hear remote state changes between turns

> Derived from [`requirements.md`](requirements.md) and [`design.md`](design.md), before
> `tasks.md`. Authored at `test-planning`, completed at `verification`.
>
> **This file is executable content.** It names commands an agent will run; review it
> like code. No credential is needed: every test runs offline over fakes and Temporal's
> test server.

The work is proved in four layers:

- **Unit:** the pure pieces.
- **Integration:** two in-process harnesses, with real pushes travelling the real route.
- **Security:** one negative test per abuse case.
- **Contract:** the settings schema and the public API snapshots.

The other rows are `n/a`, each with its reason.

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | `push_url` (encoding, base with and without a trailing slash); `token_digest`; `remote_out` (awaiting-next-message → COMPLETED, final flags); `RemoteAgentSpec.updates` / `follow_interval` validation; `PushReceiver` refusal ordering (413, 401 without a Temporal call, 400, 401 on update failure, 204) over a fake Temporal client | `uv run pytest tests/unit` |
| T2 | Integration (scenario) | yes | Over Temporal's test server, Gherkin-documented: push registration, a third-party cancel or complete heard through push, the same through follow, `off` keeps today's behaviour, cleanup on end and on cancel, a reply cancels the follow, the parent's row and note | `uv run pytest tests/integration/agents` |
| T3 | Contract | yes | `tests/contract/snapshots/settings.schema.json` gains `updates` and `follow_interval`. The public-API snapshots (`tiny_harness.config`, `service`) are updated deliberately, and nothing else changes. | `uv run pytest tests/contract` |
| T4 | End-to-end | n/a: the e2e demos use one harness with no remote agent, and the scenario needs two harnesses and a third party. T2 runs the full HTTP route (SDK push sender → `LimitsMiddleware` → endpoint → Temporal update) in-process, which is what e2e would add. | | |
| T5 | UI / visual | n/a: no renderer changes. The parent's sub-task row already renders any state the TUI and web renderers receive (issue-25). | | |
| T6 | Snapshot | n/a beyond T3: no rendered output changes. | | |
| T7 | Performance / load | n/a: the new paths run only while a remote sub-task is parked: one `GetTask` per push, or one long-lived stream per parked task. Rates are bounded by `rate_limit_per_minute` and `follow_interval` (≥ 1 s), as asserted in T8. | | |
| T8 | Security / abuse case | yes | Abuse cases 1–9: missing token, wrong token, unknown id, a `TaskWorkflow` id, an ended stand-in (all the same `401`, no state change); constant-time compare (code-level: `hmac.compare_digest` asserted by test); a valid token naming another remote task; oversize and malformed bodies; a forged terminal body ignored in favour of `GetTask`; the token absent from history, logs and the store; the URL built from the local id only | `uv run pytest tests/security/test_remote_push.py` |
| T9 | Accessibility | n/a: no user interface changes. | | |
| T10 | Migration / upgrade | yes (narrow) | An existing `[[agents]]` entry without the new keys still loads, with `updates = "auto"`. A stand-in started before this change is out of scope (requirements § Out of scope). | `uv run pytest tests/unit/test_config_agents.py` |
| T11 | Manual exploratory | n/a: no surface a person exercises differently, and T2 drives the same code over the same transport. | | |
| T12 | Static | yes | ruff, pyright strict, markdownlint over all files, as CI | `uv run pre-commit run --all-files` |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1.2, abuse 9 | `push_url` from the base URL and the local id |
| T1 | R2.5 | `remote_out` maps awaiting-next-message to COMPLETED |
| T1 | R4.1, R4.5 | invalid `updates`, `follow_interval` below 1 s → `ConfigError` |
| T1 | R2.1–2.2, abuse 1, 5 | receiver ordering over a fake client |
| T2 | R1.1–1.4 | `Scenario: A parked remote task gets a push config pointing at this server` |
| T2 | R2.2–2.4, R2.6–2.7 | `Scenario: A third party cancels a parked remote sub-task and the parent hears of it through push` |
| T2 | R2.7 | `Scenario: The parent's row moves and its model is told only of an ending or a new question` |
| T2 | R3.1–3.2, R4.3 | `Scenario: Without push the stand-in follows the parked task and hears a third-party completion` |
| T2 | R3.4 | `Scenario: A reply while following cancels the follow and starts a turn` |
| T2 | R4.4 | `Scenario: updates = "off" keeps today's behaviour` |
| T2 | R5.1, R5.3 | `Scenario: The push config is deleted when the stand-in ends or is cancelled` |
| T2 | R1.5 | `Scenario: A failed registration falls back to follow` |
| T8 | abuse 1–9 | one test per case |
| T10 | R4.1 | a legacy `[[agents]]` entry loads with the defaults |

## Verification environment

- **Repository:** this one, branch `loop/issue-27`. There is a single repository
  (`the-loop graph repos issue-27` declares none).
- **Runtime:** Python 3.14 via `uv`; `uv sync` installs the locked dependencies.
- **Temporal:** the time-skipping test server that `temporalio.testing` downloads into
  `~/.cache/temporalio`. No network access is needed after the first download.
- **Services:** none outside the process. Both harnesses run in-process, over
  `httpx.ASGITransport`.
- **Credentials:** none.
- **Bring-up:** `uv sync && uv run pytest tests/unit tests/contract tests/security tests/integration/agents`.
  If `/tmp` is full on the verification host, set `TMPDIR` under `~/.cache` first.

## Evidence plan

Committed under `evidence/`, as markdown with the raw output in fenced blocks:

- `unit.md`, `integration.md`, `contract.md`, `security.md`: the command and its output for
  each row.
- `static.md`: the pre-commit run.
- `scenarios.md`: `the-loop scenarios --root "$PWD" --glob 'tests/integration/agents/*.py'
  --format markdown`.
- Redaction: the push tokens the tests generate are random and never printed. If one
  appears in any output, that is a T8 failure, not something to redact.

## Verification activities

- [x] T1 unit: `uv run pytest tests/unit -q`
- [x] T2 integration: `uv run pytest tests/integration/agents -v`
- [x] T2 regression: `uv run pytest tests/integration -q`
- [x] T3 contract: `uv run pytest tests/contract -q`
- [x] T8 security: `uv run pytest tests/security -v`
- [x] T10 migration: included in T1 (`tests/unit/test_config_agents.py`)
- [x] T12 static: `uv run pre-commit run --all-files`
- [x] Scenario table: `the-loop scenarios --root "$PWD" --glob 'tests/integration/agents/*.py' --format markdown`

## Verification results

All activities ran at commit `2dc0dac` on 2026-10-12 and passed.

| Activity | Command | Outcome | Evidence |
|----------|---------|---------|----------|
| T1 / T10 unit | `uv run pytest tests/unit -q` | 547 passed | [unit.md](evidence/unit.md) |
| T2 integration | `uv run pytest tests/integration/agents -v` | 9 passed (8 new scenarios) | [integration.md](evidence/integration.md) |
| T2 regression | `uv run pytest tests/integration -q` | 100 passed | [regression.md](evidence/regression.md) |
| T3 contract | `uv run pytest tests/contract -q` | 36 passed; the settings schema and `tiny_harness.config` snapshots were updated on purpose | [contract.md](evidence/contract.md) |
| T8 security | `uv run pytest tests/security -v` | 79 passed, including the 8 tests in `test_remote_push.py` | [security.md](evidence/security.md) |
| T12 static | `uv run pre-commit run --all-files` | every hook passed | [static.md](evidence/static.md) |
| Scenario table | `the-loop scenarios … --format markdown` | 9 scenarios listed, each linked to a requirement | [scenarios.md](evidence/scenarios.md) |

Stability: the new integration and security files were each run three times in a row
during implementation with identical results, and the full suite twice (762 passed both
times).

What verification changed in the spec. Three findings from the tests went back into
`requirements.md` and `design.md` before this record was written:

- **R1.6:** `X-Participant-Id` on every remote task call. Without it, a tiny-harness peer
  answered "task not found". This was also a latent bug in replies to a parked peer.
- **R2.9:** re-fetch while the fetch disagrees with the push's claimed state. A remote
  pushed before its own `GetTask` showed the change.
- **Abuse case 7:** the SDK's DEBUG request-body log is dropped.

The "no history" wording was also corrected: a rejected update can leave an empty
workflow task, but never an update or an activity.
