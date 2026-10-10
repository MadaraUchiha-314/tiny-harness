---
type: testing-plan
phase: test-planning
workItem: issue-3
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

# Testing plan: tiny-harness: A tiny agent harness

> Derived from the approved `requirements.md`/`bugfix.md` and `design.md`, **before**
> `tasks.md` — each task's `_Test:_` names a row of the matrix below. Authored at the
> `test-planning` node and **completed at the `verification` node**: the same file is
> written once as a plan and once as a record, so intent and outcome sit in one diff.
> See `reference/testing.md`.
>
> **This file is executable content.** It names commands an agent will run, so review it
> like code. Credentials appear **by reference only** (env var name, secret-store key),
> never by value.

The harness is proved at four levels: unit and contract tests pin every public interface
from `design.md`; integration tests run the workflows in Temporal's test environment and
the A2A server in-process; the abuse-case suite is the security section of the design
turned into negative tests; and the end-to-end demo of Requirement 24 runs on Temporal
Cloud and `gpt-6.1-sol` with both renderers, including a worker kill. Everything runs
through the repository's own commands (`uv run pytest`, the pre-commit hooks, `bun` for the
web renderer); nothing here needs a runner the-loop brings.

## Test matrix

> One row per candidate testing type. A type that does not apply is marked `n/a`
> **with a reason** — an unexplained blank is not a decision. Nothing here is mandatory
> in itself; the matrix is **work-item dependent**, and most work items use a handful of
> rows. Add types the catalogue does not list (chaos, load-soak, i18n, data-migration
> dry-run…) as extra rows.

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | every entity, loader, model adapter, the registry, hook manager, plan validator, context window manager, compaction, redactor, config; through public interfaces with fakes (`FakeLLM`, `FakeSystemOne`, in-memory `Store`, scripted stdio MCP server) | `uv run pytest tests/unit -q` (pre-commit hook and CI `checks` job) |
| T2 | Integration (scenario) | yes | the task workflow and activities in `temporalio.testing.WorkflowEnvironment` (time-skipping), the A2A server in-process with the `a2a-sdk` client, plugin and skill loading from fixture directories, MCP over stdio, heartbeat schedule; Gherkin-documented | `uv run pytest tests/integration -q` (CI `integration` job) |
| T3 | Contract | yes | the public API snapshot of every interface named in `design.md` (entities, hooks and contexts, registry, tools, models, store, channels, config); the two tiny-harness A2A extension JSON schemas against committed fixtures; the hook-context and `Settings` JSON schemas | `uv run pytest tests/contract -q` (CI `checks` job) |
| T4 | End-to-end | yes | Requirement 24: both renderers on one instance, plan + `gpt-6.1-sol` + MCP tool + terminal state, two-turn help request, an A2UI action, a worker kill mid-task on Temporal Cloud with no duplicated LLM or tool call | `uv run python -m examples.demo` with the environment below, driven by `tests/e2e/test_demo.py` (`uv run pytest tests/e2e -q -m e2e`) |
| T5 | UI / visual | yes | the implemented web and TUI renderers match the locked prototypes state for state (`WORKING`, `INPUT_REQUIRED`, A2UI card rendered by `@a2ui/react`'s default catalog, placeholder, task/plan/trace panes) | web: `bun run --cwd renderers/web test:visual` (Playwright, Chromium); TUI: `uv run pytest tests/ui -q` (pytest-textual-snapshot) |
| T6 | Snapshot | yes | serialized shapes that must not drift: the agent card JSON, the extension schemas under `docs/a2a/ext/`, the default system prompt sections, Textual screen snapshots (shared with T5) | `uv run pytest tests/contract -q -k snapshot` |
| T7 | Performance / load | n/a — the demo is single-user and no latency or throughput budget is a requirement; the one cost figure (prompt cache hit) is captured as T4 evidence | | |
| T8 | Security / abuse case | yes | one negative test per row of `design.md` §Security design's abuse-case table (cases 2–9; case 1 is the perimeter's, decision-003) | `uv run pytest tests/security -q` (CI `checks` job) |
| T9 | Accessibility | yes | web: axe-core through Playwright on the three main states, keyboard-only walk of the composer, tabs and A2UI card; TUI: every action reachable by the documented keys (snapshot-driven) | `bun run --cwd renderers/web test:a11y`; `uv run pytest tests/ui -q -k keys` |
| T10 | Migration / upgrade | n/a — the package has no users and no persisted data yet (`0.1.0` ships one example function); the SQLite schema is new | | |
| T11 | Manual exploratory | yes | the demo walkthrough with a written procedure, performed by the owner on their machine with the keyring secrets, recording what automation did not reach (feel of the TUI, latency of streaming, readability of the plan pane) | procedure in `evidence/manual-walkthrough.md` |
| T12 | Crash recovery (chaos) | yes | `kill -9` the worker during an `invoke_tool` activity and during an `INPUT_REQUIRED` wait; the task completes after restart, the trace shows one LLM span and one tool span per step | part of T4 (`tests/e2e/test_crash_recovery.py`) |
| T13 | Type and lint gates | yes | pyright strict with zero errors and no `Any` (a grep gate in CI fails on `Any` outside `tests/`), ruff, markdownlint | `uv run pre-commit run --all-files` (pre-commit hook and CI `checks` job) |

## Scenarios & requirement trace

> Which requirement each row proves, and — for integration rows — the Gherkin
> `Scenario:` titles the tests will carry (`testing.gherkinDocstrings`). Do not paste the
> scenario table here: `the-loop scenarios --format markdown` renders it for the reviewer
> briefing.

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1 | registry resolves `(id, version)` with PEP 440 and `*`; unknown ref raises `EntityNotFoundError`; remote entry without protocol refused |
| T1 | R2 | hook chain order by priority; `pre` replaces input, `post` replaces output, `in` default body overridden by lower priority; `HookAbort` cancels; single-tool-call veto |
| T1 | R3 | manifest validation, namespace directory parsing, path escape rejected, `${PLUGIN_ROOT}` expanded in `args`/`env`/`cwd` and never in `command`, duplicate `(id, version)` refused |
| T1 | R4 | default prompt loaded from the markdown file; sections replaced and extended |
| T1 | R5 | front-matter validation rules; three disclosure levels; invalid skill skipped with reason |
| T1 | R6 | tool-call schema validation; unknown tool error result; idempotency from MCP annotations; schema-hash drift refused |
| T1 | R8, R9 | task model; plan cycle rejected; sub-task tracking blocks parent completion |
| T1 | R10 | context order by stability; never-compact set survives compaction; `CompactionRecord` written; threshold triggers |
| T1 | R11 | `SqliteStore` put/get/query; write failure surfaces `StoreWriteError`; no credential field in any `Record` except the encrypted push token; `retention_sweep` deletes expired rows per kind |
| T1 | R17 | `Redactor` masks bearer tokens, `sk-` keys, `Authorization` headers and configured secret values |
| T1 | R18 | `OpenAILLM` request mapping (instructions = static prefix, `prompt_cache_key`, `store=False`, `max_retries=0`), usage parsing; `FakeSystemOne` answer shapes |
| T1 | R21 | `Settings` fails with the variable name on a missing secret; unknown key rejected |
| T2 | R19, R10, R12, R15, R8.5 | `Feature: Durable core loop` — `Scenario: a task runs the loop to completion with recorded activity results`; `Scenario: a worker crash mid-activity resumes without a second LLM call`; `Scenario: a non-idempotent tool failure is not retried`; `Scenario: activity.failed and activity.retried hooks run between workflow-managed attempts`; `Scenario: an inbox message to an executing task is drained at the next iteration`; `Scenario: compaction runs before the LLM call when the first message is over budget`; `Scenario: continue-as-new carries the mailbox, event log and pending help request`; `Scenario: a parent waits for an unresolved sub-task before completing` |
| T2 | R12, R13 | `Feature: Help requests` — `Scenario: a reply on the channel resumes an INPUT_REQUIRED task`; `Scenario: a need that blocks on another participant's work creates a sub-task`; `Scenario: a non-member's channel message is rejected` |
| T2 | R14, R15 | `Feature: A2A server` — `Scenario: SendStreamingMessage streams a Task then status updates through the bridge`; `Scenario: GetTask and ListTasks read the workflow`; `Scenario: an unadvertised extension is rejected`; `Scenario: returnImmediately returns after the task exists`; `Scenario: push notification configs receive status updates`; `Scenario: cancel emits CANCELED` |
| T2 | R16 | `Feature: Heartbeat` — `Scenario: a schedule tick forwards a pull-channel message to its task` |
| T2 | R3, R5, R6 | `Feature: Plugins` — `Scenario: a directory plugin registers its skills, MCP tools, hooks and prompts`; `Scenario: a programmatic plugin registers the same components`; `Scenario: a loaded skill's MCP tools appear and disappear with load and unload` |
| T2 | R7 | `Feature: Remote agents` — `Scenario: delegation to a remote A2A agent tracks the sub-task state`; `Scenario: a card with an unknown required extension is refused` |
| T2 | R17 | `Feature: Observability` — `Scenario: one span per operation with GenAI attributes crosses the workflow boundary` |
| T3 | R23, R8.3, R13.4, R2, R21 | API snapshot; task and channel extension schemas; hook-context schemas; `Settings` schema |
| T4 | R24 (all criteria), R19.11, R18.5, R10.3, non-functional Cost | the demo script; per-turn `input_tokens`, `cached_tokens`, `output_tokens` recorded; passes when no turn exceeds 12,000 input or 2,000 output and `cached_tokens ≥ 2,000` from turn two |
| T5 | R20.2–R20.6 | each prototype state reproduced by the implementation |
| T6 | R14.2, R4, R20 | agent card, extension schemas, prompt sections, Textual screens |
| T8 | Security considerations, abuse cases 2–9 | `test_injected_tool_call_not_executed`, `test_role_change_requires_admin`, `test_unknown_tool_rejected`, `test_plugin_path_escape_rejected`, `test_command_with_expansion_rejected`, `test_non_member_rejected_without_task_existence`, `test_foreign_task_get_list_subscribe_cancel_not_found`, `test_remote_card_with_unknown_required_ext_refused`, `test_redactor_masks_tokens`, `test_ingress_redacted_before_history`, `test_push_token_encrypted_at_rest`, `test_oversized_request_not_persisted`, `test_schema_drift_refuses_invoke`, `test_unknown_a2ui_action_discarded` |
| T9 | R20 (non-functional: accessibility) | axe-core clean on the three states; keyboard walk |
| T11 | R24 | the written walkthrough |
| T12 | R19.2, R19.6, R24.5 | two kill points (during an idempotent tool activity; during the `INPUT_REQUIRED` wait), trace evidence; the at-least-once window for an LLM call stated in `design.md` is not claimed |
| T13 | R22.2 | zero pyright errors, no `Any` |

## Verification environment

> What the verification needs in order to run. the-loop **facilitates** verification; it
> does not own your environment — name the project's own commands here rather than
> expecting the loop to model the setup. Where an operator document already describes
> this, link the doc registered in `customInstructions.docs` instead of restating it.

- **Repositories:** this repository only, branch of the PR under verification.
- **Services / containers:**
  - T1, T3, T6, T8, T13: none.
  - T2: Temporal's time-skipping test server, started by
    `temporalio.testing.WorkflowEnvironment.start_time_skipping()` in a session fixture
    (downloads the test-server binary once; `TEMPORAL_TEST_SERVER_PATH` overrides). MCP:
    the fixture server `tests/fixtures/mcp_orders.py` over stdio. LLM: `FakeLLM`.
  - T4, T11, T12: Temporal Cloud namespace `tiny-harness.gtebu` at
    `tiny-harness.gtebu.tmprl.cloud:7233`; OpenAI `gpt-6.1-sol`; the demo plugin's two
    stdio MCP servers (`examples/demo/mcp_orders.py`, `examples/demo/mcp_policy.py`); the
    harness server (`uv run tiny-harness serve --config examples/demo/config.toml`), one
    worker (`uv run tiny-harness worker --config examples/demo/config.toml`), the web
    renderer (`bun run --cwd renderers/web dev`), the TUI
    (`uv run tiny-harness tui http://localhost:8080`).
  - T5, T9: Chromium (`/usr/bin/chromium` locally, Playwright's in CI) and Bun for the
    web renderer; no browser for the TUI snapshots.
- **Fixtures & data:** `tests/fixtures/plugins/` (valid, malformed manifest, path escape,
  duplicate id), `tests/fixtures/skills/`, `tests/fixtures/a2a/` (cards with and without
  required extensions, extension payloads), `tests/fixtures/openai/` (recorded Responses
  API bodies for the adapter's parsing tests), `examples/demo/` (plugin, config, the
  demo task "refund order #48213").
- **Credentials:** **by reference only** — `TEMPORAL_API_KEY` (keyring:
  `secret-tool lookup service temporal project tiny-harness`), `OPENAI_API_KEY`
  (keyring: `secret-tool lookup service openai project tiny-harness`). `TYPESAFE_API_KEY`
  is not needed (no Jev client in this work item). Tests needing them are marked `e2e`
  and skip with a reason when a variable is absent; they never pass silently.
- **Bring-up:** `uv sync --locked && uv run pre-commit install`; for T4:
  `export TEMPORAL_API_KEY="$(secret-tool lookup service temporal project tiny-harness)"`,
  `export OPENAI_API_KEY="$(secret-tool lookup service openai project tiny-harness)"`,
  then `uv run tiny-harness serve …`, `uv run tiny-harness worker …`,
  `bun install --cwd renderers/web && bun run --cwd renderers/web dev`.
  **Tear-down:** stop the three processes; `uv run tiny-harness schedules delete
  tiny-harness-heartbeat` removes the heartbeat schedule from the namespace.
- **If bring-up fails:** record it under Verification results, leave the dependent
  activities unticked, and escalate — do not pass the gate on an environment that
  never came up.

## Evidence plan

> What will be captured, and where. Evidence is committed under
> `<specDir>/<id>/evidence/`; a link to a CI run that expires or to a local path is not
> evidence. **Textual evidence is markdown (`.md`), never `.txt`** — titled, one section
> per command, raw output in fenced blocks. Binary captures keep their own formats.
>
> **Redact before committing.** Captured output and screenshots routinely contain tokens,
> cookies, personal data and internal hostnames, and this directory is as public as the
> repository. If a capture cannot be redacted, do not commit it — say so in the results
> row instead. A secret that reaches a commit is rotated, not merely edited out.

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1 | test summary (counts, duration), one section per stacked PR layer | `unit.md` |
| T2 | scenario table (`the-loop scenarios --glob 'tests/integration/**' --format markdown`) + run output | `integration.md` |
| T3, T6 | contract and snapshot run output; the committed schemas under `docs/a2a/ext/` are the artifacts | `contract.md` |
| T4 | the demo run: command transcript, the task's final A2A `Task` JSON, usage lines showing `cached_tokens` on turn two, the trace export (OTLP file exporter, JSON, redacted) | `e2e.md`, `e2e/trace.json` |
| T5, T9 | screenshots of each verified state for web and TUI, axe report, an animated capture of the two-turn help flow on each renderer | `ui/web-<state>.png`, `ui/tui-<state>.png`, `ui/axe.md`, `ui/web-multi-turn.gif`, `ui/tui-multi-turn.gif` |
| T8 | abuse-case suite output | `security.md` (also the record the `security-review` node reads) |
| T11 | the walkthrough procedure and the owner's notes | `manual-walkthrough.md` |
| T12 | kill timestamps, worker logs before and after, the trace showing one LLM and one tool span per step across the restart | `crash-recovery.md` |
| T13 | pre-commit run output, pyright summary, the `Any` grep gate output | `gates.md` |

Redaction: Temporal namespace and address are public configuration and stay; API keys,
`Authorization` headers and any `tmprl`/`sk-` shaped value are replaced by `[REDACTED]`
by the same `Redactor` the harness uses, run over every capture before commit.

## Verification activities

> The checklist the `verification` node gates on (`checkmarks: complete`). One line per
> thing that will actually be executed. Tick a line **only** when it has been run and its
> evidence recorded below. An activity that cannot be executed is **not** ticked: record
> why under Verification results and either replan this matrix (with the reason) or
> escalate.

- [x] T13 — `uv run pre-commit run --all-files` (lint, format, pyright strict, unit tests, markdownlint) and the `Any` grep gate
- [x] T1 — `uv run pytest tests/unit -q`
- [x] T3 — `uv run pytest tests/contract -q`
- [x] T6 — `uv run pytest tests/contract -q -k snapshot`
- [x] T8 — `uv run pytest tests/security -q`
- [x] T2 — `uv run pytest tests/integration -q` and `the-loop scenarios --glob 'tests/integration/**' --format markdown`
- [x] T5 — `bun run --cwd renderers/web test:visual` and `uv run pytest tests/ui -q`
- [x] T9 — `bun run --cwd renderers/web test:a11y` and `uv run pytest tests/ui -q -k keys`
- [x] T4 — bring-up above, then `uv run pytest tests/e2e -q -m e2e` (runs `examples.demo` end to end, captures screenshots and the trace)
- [x] T12 — `uv run pytest tests/e2e -q -m e2e -k crash_recovery` (kills the worker at the two points and restarts it)
- [ ] T11 — the walkthrough in `evidence/manual-walkthrough.md`, performed and annotated by the owner

## Verification results

> Authored empty at `test-planning` (as `_Not yet executed._`) and filled at
> `verification`. One row per executed activity: the exact command or procedure, the
> outcome, and a link to the committed evidence.

Executed on 2026-10-10 on branch `loop/issue-3-l9-demo` (the head of the stacked
series, every lower layer merged forward), on the owner's machine: Temporal Cloud namespace
`tiny-harness.gtebu`, OpenAI `gpt-6.1-sol`, system Chromium. Secrets came from the
keyring; every capture under `evidence/` was redacted by value before commit.

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| T13 | `uv run pre-commit run --all-files`; `uv run pyright`; the `Any` grep | all hooks passed; pyright 0 errors; the word `Any` appears only in two docstrings | [gates.md](evidence/gates.md) |
| T1 | `uv run pytest tests/unit -q` | 191 passed in 4.2 s | [unit.md](evidence/unit.md) |
| T3 | `uv run pytest tests/contract -q` | 29 passed | [contract.md](evidence/contract.md) |
| T6 | `uv run pytest tests/contract -q -k snapshot` | 14 passed (agent card, task and channel schemas, 12 intrinsic schemas, Settings schema) | [contract.md](evidence/contract.md) |
| T8 | `uv run pytest tests/security -q` | 24 passed, abuse cases 2–9 | [security.md](evidence/security.md) |
| T2 | `uv run pytest tests/integration -q`; `the-loop scenarios --root . --glob 'tests/integration/**/*.py' --format markdown` | 32 passed in 51 s; 31 Gherkin scenarios listed | [integration.md](evidence/integration.md) |
| T5 | `bun run --cwd renderers/web test:visual`; `uv run pytest tests/ui -q`; live captures of both surfaces | 4 passed; 9 passed (4 snapshots); six states captured per surface | [ui/axe.md](evidence/ui/axe.md), `evidence/ui/web-*.png`, `evidence/ui/tui-*.png`, `evidence/ui/web-multi-turn.gif`, `evidence/ui/tui-multi-turn.gif` |
| T9 | `bun run --cwd renderers/web test:a11y`; `uv run pytest tests/ui -q -k keys` | 2 passed (no axe violations, every control reachable); 4 passed | [ui/axe.md](evidence/ui/axe.md) |
| T4 | `uv run pytest tests/e2e -q -m e2e` with the bring-up above (Temporal Cloud, `gpt-6.1-sol`) | 3 passed in 4 min 16 s: SUBMITTED → WORKING → A2UI artifact → INPUT_REQUIRED (card action) → INPUT_REQUIRED (text reply) → COMPLETED; `ship_replacement` once; 17 chat spans, cached tokens from call 2; no secret in trace or logs | [e2e.md](evidence/e2e.md), [e2e/trace.json](evidence/e2e/trace.json) |
| T12 | `uv run pytest tests/e2e -q -m e2e -k crash_recovery` | 2 passed: kill during `get_order` at 22.6 s (attempt timed out, retried on the new worker; `invoke_llm` 15 scheduled / 15 completed) and kill in INPUT_REQUIRED at 146.9 s (every activity one attempt); task COMPLETED both times | [crash-recovery.md](evidence/crash-recovery.md) |
| T11 | the walkthrough in `evidence/manual-walkthrough.md` | not yet performed by the owner; stays unticked | [manual-walkthrough.md](evidence/manual-walkthrough.md) |
| | | | |

**Not executed:** none yet.

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109). Append-only and attributed: an approval never silently
> discards a reviewer's suggestions, and the feedback travels with the document
> it concerns rather than living in a side-channel tracker.

### 2026-10-09 — approved

**@MadaraUchiha-314** wrote:

approved design
