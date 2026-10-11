---
type: testing-plan
phase: test-planning
workItem: issue-25
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

# Testing plan: Make the CLI/TUI experience seamless

> Derived from the approved [`requirements.md`](requirements.md) and
> [`design.md`](design.md), **before** `tasks.md`. Each task's `_Test:_` names a row of
> the matrix below. Authored at the `test-planning` node and **completed at the
> `verification` node**.
>
> **This file is executable content.** It names commands an agent will run, so review it
> like code. Credentials appear **by reference only**.

The work is proved by the repository's own layers:

- **Unit:** the new modules.
- **Integration:** over Temporal's test server, for the lifecycle, completion and command
  flows.
- **Contract:** for the three extensions and the public API.
- **Security:** one negative test per abuse case.
- **UI:** TUI snapshots and keys; web vitest, Playwright visual and axe.
- **E2E:** the offline Ollama demo, so no secret is needed.
- **Manual:** a clean-`HOME` first run of the installed wheel.

Performance and migration rows are `n/a`, each with its reason.

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | `home.py` (resolution, default text, safe creation, modes, refusals); CLI parser (bare command, epilog, `--help` never creates); `CoreLoop._finish` by lifecycle; `with_state` sub-state write/clear; the command parser; each built-in command; `_ForCommand`; `CommandRegistry` duplicate/invalid names; the plugin loader's `commands.json` (resolve-before-hooks, skips); `[openai] models` / `reasoning_effort` validators; `ModelCatalog.settings_for`; each adapter's effort mapping and byte-identical requests when unset; `model.ts` fold of the sub-state | `uv run pytest tests/unit`; `cd renderers/web && bun run test` |
| T2 | Integration (scenario) | yes | Workflow behaviour over Temporal's test server, Gherkin-documented: lifecycle, completion, dispatch, commands, settings, inheritance, plugin commands | `uv run pytest tests/integration` |
| T3 | Contract | yes | Agent-card snapshot (status and commands extensions); JSON Schemas `docs/a2a/ext/{task,status,commands}.json` and `docs/plugins/commands.json` generated from the models; public-API snapshots (`config`, `hooks`, `plugins`, `entities`, `service`, new `home`, `models`) | `uv run pytest tests/contract` |
| T4 | End-to-end | yes | The offline demo (embedded Temporal plus a loopback Ollama), updated: a turn ends `INPUT_REQUIRED · awaiting-next-message`, a second message continues the same task, `/status` answers without a model call, and an explicit complete ends it `COMPLETED` | `uv run pytest tests/e2e/test_demo_ollama.py -m e2e` |
| T5 | UI / visual | yes | TUI: the top bar's state and sub-state, Complete/Cancel keys, `/` suggestion and hint line, sub-task open and back (`ScriptedClient`). Web: header badges, Complete/Cancel enabled states, command listbox, sub-task links, parent link, matched against the locked prototypes | `uv run pytest tests/ui`; `cd renderers/web && bun run test:visual` |
| T6 | Snapshot | yes | TUI SVG snapshots for the new states (input-required with sub-state, completed, sub-task open); web Playwright screenshots (light, dark, phone, command listbox) | `uv run pytest tests/ui`; `bun run test:visual` (strict with `TINY_HARNESS_VISUAL_STRICT=1`) |
| T7 | Performance / load | n/a: no hot path changes cost. A command replaces a model call with one activity, and the dispatcher adds one `intake` call that already ran per message. | | |
| T8 | Security / abuse case | yes | One negative test per abuse case 1–10 in `design.md` § Security design, plus the server-controlled-field refusal and validator-before-interrupt | `uv run pytest tests/security` |
| T9 | Accessibility | yes | axe on the web header controls and the composer combobox; keyboard reach of Complete, Cancel, listbox options, sub-task links and ← Parent; TUI: every action has a key | `cd renderers/web && bun run test:a11y`; `uv run pytest tests/ui/test_tui_keys.py` |
| T10 | Migration / upgrade | yes (narrow) | A task persisted before this change (no `lifecycle`, no status key) still loads, `GetTask` answers, and its lifecycle is derived from `parent_tasks`. An existing `--config` file still loads unchanged. | `uv run pytest tests/unit/core/test_task_compat.py tests/unit/test_config.py` |
| T11 | Manual exploratory | yes | Install the built wheel into a fresh venv with a throwaway `HOME`, run bare `tiny-harness` against the local Ollama: the file is created with `0700`/`0600`, the TUI opens, one conversation spans several messages, `/model`, `/effort`, `/status`, `/sub-task`, open and back, `ctrl+d`. Then `tiny-harness --config demo.toml --help` names the flag file and `~/.tiny-harness` is untouched. | the procedure in Verification activities |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1.2, R1.5 | bare `tiny-harness` → `tui`; epilog names the file and its origin; `--help` creates nothing |
| T1 | R2.1–2.8 | flag wins and the default is not touched; missing default created; existing default not rewritten; invalid default not replaced; the default text loads as `Settings` with absolute paths |
| T1 | R3.1, R3.4 | `_finish` → `await_next_message` for `conversation`, `decide_completion` for `delegated`; lifecycle derived when absent |
| T1 | R6.1, R6.3, R6.5, R6a.6–6a.8 | command regex; unregistered `/x` is ordinary; duplicate and invalid names raise; `commands.json` skips (bad name, unknown hook, extra points, shared hook) |
| T1 | R7, R8 | `models` must contain `model`; `settings_for` precedence; Responses `reasoning`, Chat `reasoning_effort`, Anthropic `output_config.effort`; no field when unset |
| T2 | R3.1, R3.3, R3.6 | `Scenario: A reply leaves a conversation task awaiting the next message` |
| T2 | R3.3 | `Scenario: The next message resumes the same task and clears the sub-state` |
| T2 | R3.2 | `Scenario: ask_participant parks the task awaiting an answer` |
| T2 | R3.4 | `Scenario: A delegated sub-task still completes when its loop ends` |
| T2 | R3.4 | `Scenario: A participant task still completes on the assignee's answer, and a command does not` |
| T2 | R5.1, R5.2, R5.6 | `Scenario: A participant completes a task and every subscriber sees COMPLETED` |
| T2 | R5.2 | `Scenario: Completing a task interrupts the turn in progress` |
| T2 | R5.3 | `Scenario: Completing or cancelling a terminal task names its state` |
| T2 | R5.4 | `Scenario: Completion is refused while a sub-task is open` |
| T2 | R6.2, R10.1, R10.2 | `Scenario: A command runs without invoking the model and the state is unchanged` |
| T2 | R6.2 | `Scenario: A command sent during a running turn replies without joining the history` |
| T2 | R6.6 | `Scenario: A failing command replies with the error and changes nothing` |
| T2 | R7.3, R8.3 | `Scenario: /model and /effort change the next model request, compaction and help included` |
| T2 | R7.3 | `Scenario: Sub-tasks inherit the parent's model and effort` |
| T2 | R9.1, R9.2 | `Scenario: /sub-task creates a linked conversation task and replies with its id` |
| T2 | R6a.2–6a.5 | `Scenario: A plugin command overrides a built-in and a pre hook can refuse it` |
| T2 | R6a.9 | `Scenario: A remote command executor that fails leaves the task unchanged` |
| T3 | R4.1–4.4, R6.7 | card lists status (`required: false`) and commands extensions with the registered specs; `status.json` documents both values without a closed enum |
| T4 | R1.3, R3, R5, R10 | demo turn ends `INPUT_REQUIRED · awaiting-next-message`; continue; `/status`; complete |
| T5, T6 | R5.5–5.7, R6.7, R9.4 | TUI and web states listed under T5 |
| T8 | Security abuse cases 1–10 | see the next table |
| T9 | NFR accessibility | axe and keyboard reach |
| T10 | NFR backwards compatibility | pre-change task loads; old config loads |
| T11 | R1, R2, R5–R10 | manual first-run walkthrough |

**Abuse cases → negative tests (T8).**

| Abuse case | Test |
|------------|------|
| 1 | `/model evil-model` refused and the model unchanged; a first-message `task` envelope carrying `model` (or `lifecycle`, `reasoning_effort`) refused with no task created; the same envelope on an existing task not accepted |
| 2 | `/effort extreme` refused |
| 3 | command, complete and cancel from a non-member → task not found |
| 4 | watcher complete (idle and mid-turn: the turn keeps running), cancel, `/model x`, `/effort x`, `/sub-task` refused, state unchanged |
| 5 | `/sub-task $(rm -rf ~)`, `/model ../../x`, arguments with control characters → stored as text or refused; no process spawned, no path opened |
| 6 | `/sub-task` beyond `rate_limit_per_minute` → 429 |
| 7 | home or config as a symlink, or owned by another uid (simulated with an injected `geteuid`) → exit 2, nothing written |
| 8 | created directory `0700` and file `0600` asserted with `stat` |
| 9 | `/unknown hi` reaches the model as ordinary text |
| 10 | a remote command executor (JSON-RPC stub) receives only its own command, with secrets scrubbed; a command-owned hook with extra points is skipped |

## Verification environment

- **Repositories:** this repository only, at the PR branch `loop/issue-25`.
- **Services:** the integration tests start Temporal's test server themselves.
  - T4 and T11 use an embedded Temporal (the cached CLI).
  - T4 and T11 need a local Ollama answering on `127.0.0.1:11434` with `qwen3:1.7b`
    pulled; the machine has one.
  - T5 and T9 (web) need Chromium for Playwright (`bun x playwright install chromium`).
- **Fixtures & data:**
  - The TUI prototype fixtures in `tests/ui/prototype.py` gain the new states.
  - The web fixture `src/fixtures/prototype.ts` gains the sub-state and commands.
  - T10 writes a pre-change task record (no `lifecycle`, no status key) through
    `SqliteStore.put`.
  - T11 uses `HOME=$(mktemp -d)`.
- **Credentials:** none. T4 and T11 run with `[openai] base_url` set to the loopback
  Ollama, so `OPENAI_API_KEY` is not needed; `TEMPORAL_API_KEY` is unset.
- **Bring-up:** `uv sync --locked`, plus `cd renderers/web && bun install --frozen-lockfile`.
  For T11, `uv build` and then `uv venv` + `uv pip install dist/*.whl` in a temp directory.
- **Tear-down:** the tests stop what they start. T11 removes its temp `HOME` and venv.
- **Temp space:** `/tmp` on this machine has a per-user quota that other sessions fill.
  Run with `TMPDIR` and pytest `--basetemp` under `~/.cache/`.
- **If bring-up fails:** record it under Verification results, leave the dependent
  activity unticked, and escalate on the PR.

## Evidence plan

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1 | test summaries (counts, duration), Python and web | `unit.md` |
| T2 | `the-loop scenarios --format markdown` table + run output | `integration.md` |
| T3 | run output; snapshot diffs summarised | `contract.md` |
| T4 | run output with the observed state sequence | `e2e.md` |
| T5, T6 | TUI SVG snapshots; web screenshots of each verified state (light, dark, phone, listbox open, completed); a GIF of the flow: reply → `/sub-task` → open → back → Complete | `ui/*.svg`, `ui/*.png`, `ui/task-controls-flow.gif`, indexed in `ui.md` |
| T8 | run output, one line per abuse case | `security.md` |
| T9 | axe report summary and keyboard-reach results | `accessibility.md` |
| T10 | run output | `migration.md` |
| T11 | transcript of the walkthrough with `stat` output for the modes; the home path redacted to `~` | `manual.md` |

All output is redacted before commit: the home path becomes `~`, and no host name other
than `127.0.0.1` appears.

## Verification activities

- [ ] T1: `uv run pytest tests/unit` and `cd renderers/web && bun run test`
- [ ] T2: `uv run pytest tests/integration`, then
  `the-loop scenarios --root "$PWD" --glob 'tests/integration/**/*.py' --format markdown`
- [ ] T3: `uv run pytest tests/contract`
- [ ] T4: `uv run pytest tests/e2e/test_demo_ollama.py -m e2e`
- [ ] T5/T6: `uv run pytest tests/ui` and `cd renderers/web && bun run test:visual`
- [ ] T8: `uv run pytest tests/security`
- [ ] T9: `cd renderers/web && bun run test:a11y`
- [ ] T10: `uv run pytest tests/unit/core/test_task_compat.py tests/unit/test_config.py`
- [ ] T11: the manual first-run walkthrough below

**T11 procedure.**

1. Build and install:
   `uv build && uv venv ~/.cache/i25/w && uv pip install -p ~/.cache/i25/w dist/*.whl`.
2. Run `HOME=$(mktemp -d -p ~/.cache)` with `~/.cache/i25/w/bin/tiny-harness` and no
   arguments. Expect stderr `created default configuration …/.tiny-harness/config.toml`,
   then:
   - check `stat -c %a` on the directory (`700`) and the file (`600`);
   - edit `[openai] base_url` to the loopback Ollama and `model` to `qwen3:1.7b`.
3. Re-run and check each of these:
   - Send two messages: one task, `INPUT_REQUIRED · awaiting-next-message` between them.
   - `/status`: no model call.
   - `/effort low`.
   - `/sub-task …`: open it with `enter`, return with `f4`.
   - `ctrl+d`: `COMPLETED`; the keys are then inert.
4. `tiny-harness --config examples/demo/config.ollama.toml --help`: the epilog names the
   flag file, and `ls -a $HOME` shows no new entries.
5. Make `$HOME/.tiny-harness` a symlink. `tiny-harness` exits 2 naming the path.

## Verification results

_Not yet executed._

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| | | | |

**Not executed:** none yet.

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109). Append-only and attributed: an approval never silently
> discards a reviewer's suggestions, and the feedback travels with the document
> it concerns rather than living in a side-channel tracker.
