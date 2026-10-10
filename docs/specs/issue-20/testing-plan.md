---
type: testing-plan
phase: test-planning
workItem: issue-20
status: draft
approvedBy: []
overrides: {}
---

<!-- Written per the `the-loop:writing` skill: front-load each section's
     conclusion, draw it rather than describe it (3+ named parts -> a mermaid
     diagram), and keep the formal registers formal (EARS, abuse cases,
     RFC-2119, API contracts, schema descriptions). No length limit — length
     follows the change; the test is whether a sentence can come out without
     losing information. A gated section stays even when it is empty. -->

# Testing plan: `tiny-harness tui` never asserts a participant, so it cannot send messages

> Derived from [`bugfix.md`](bugfix.md) and [`design.md`](design.md). It names commands
> an agent will run, so review it like code.

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | `--participant` parsing, `tui_participant` resolution, exit 2 on blank / undeterminable id, `commands.tui` passing the id on the `--url` path | `uv run pytest tests/unit` |
| T2 | Integration (scenario) | yes | the real `run_tui` path sends a message under the asserted participant and reaches `COMPLETED` (regression, red before the fix); the embedded scenario takes the id from the command | `uv run pytest tests/integration/embedded` |
| T3 | Contract (OpenAPI / GraphQL SDL) | n/a — no API surface changes; the public-API snapshots do not cover the CLI or `run_tui` | | |
| T4 | End-to-end | n/a — the e2e suite drives the web renderer, which already asserts a participant; T2 plus T11 cover the TUI path end to end | | |
| T5 | UI / visual | n/a — the layout does not change; the top bar shows the same field with the real value | | |
| T6 | Snapshot | yes (regression only) | the existing TUI SVG snapshots still match, since `HarnessApp`'s default is kept | `uv run pytest tests/ui` |
| T7 | Performance / load | n/a — one string threaded through a call chain | | |
| T8 | Security / abuse case | yes | abuse case 1 (no participant → refused) and 2 (asserted id gets no extra trust) still hold: the existing refusal and access tests pass unchanged; fail-closed CLI exits are in T1 | `uv run pytest tests/security tests/integration/a2a` |
| T9 | Accessibility | n/a — no UI change | | |
| T10 | Migration / upgrade | n/a — additive optional flag; no stored state | | |
| T11 | Manual exploratory | yes | the ticket's reproduction against the demo now replies | see Verification activities |
| T12 | Full suite + static checks | yes | nothing else regressed; lint, format, types | `uv run pre-commit run --all-files`, `uv run pytest` |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1.1, R1.3 | parser accepts `--participant`; no flag → `getpass.getuser()` |
| T1 | R1.4, R1.5 | `OSError` from `getuser` and a blank flag → exit 2, stderr names `--participant` |
| T1 | R1.2, R1.6 | `commands.tui(url=…, participant="alice")` → `run_tui(url, participant="alice")` |
| T2 | R1.2, R1.6, R1.7, R2.1 | `Scenario: TUI sends a message under the asserted participant` |
| T2 | R1.6, R2.2 | `Scenario: TUI hosts its own harness in embedded mode` (stand-in takes the id from the command) |
| T8 | abuse cases 1, 2 | existing `no participant asserted` refusal and task-access tests |
| T11 | R1, R2 | ticket reproduction, remote and embedded |

## Verification environment

- **Repositories:** this repo only.
- **Services / containers:** none for T1/T6/T8. T2 starts the Temporal CLI dev server
  through `WorkflowEnvironment.start_local` (cached under the integration suite's
  `CACHE`, as in issue-17). T11 uses `uv run python -m examples.demo --config
  examples/demo/config.embedded.toml` in the background.
- **Fixtures & data:** the scripted model from `tests/integration/embedded/conftest.py`.
- **Credentials:** none. T11 in embedded mode needs no `TEMPORAL_API_KEY`. The demo's
  model uses whatever the demo config names; a scripted or local model is used if
  `OPENAI_API_KEY` is absent.
- **Bring-up:** `uv sync --locked` · **Tear-down:** stop the demo process by PID.
- **If bring-up fails:** record it below, leave the dependent activities unticked, and
  escalate on the PR.

## Evidence plan

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1, T6, T8, T12 | command, pass/fail counts, duration | `unit.md`, `regression.md` |
| T2 | red run (before the fix) and green run, plus the scenario table | `integration.md` |
| T11 | terminal transcript of the reproduction; an SVG screenshot of the TUI with a reply | `manual-walkthrough.md`, `ui/tui-participant.svg` |

## Verification activities

- [ ] T1 — `uv run pytest tests/unit`
- [ ] T2 — `uv run pytest tests/integration/embedded` (red recorded before the fix)
- [ ] T6 — `uv run pytest tests/ui`
- [ ] T8 — `uv run pytest tests/security tests/integration/a2a`
- [ ] T11 — ticket reproduction against the demo, remote (`--url`) and embedded
- [ ] T12 — `uv run pre-commit run --all-files` and `uv run pytest`

## Verification results

_Not yet executed._

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| | | | |

## Review comments
