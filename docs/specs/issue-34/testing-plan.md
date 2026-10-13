---
type: testing-plan
phase: test-planning
workItem: issue-34
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

# Testing plan: show the configured remote agents to the model

> Derived from [`requirements.md`](requirements.md) and [`design.md`](design.md), before
> `tasks.md`. Authored at `test-planning`, completed at `verification`.
>
> **This file is executable content.** It names commands an agent will run; review it
> like code. Every automated test runs offline over fakes and a local Temporal dev server.
> Only the manual run (T11) needs a credential, named by reference.

The work is proved in five layers:

- **Unit:** the pure roster builder, the context section, the intrinsic check and the
  prompt.
- **Integration:** a real `build_runtime` against a fake A2A agent, on both engines.
- **Security:** one negative test per abuse case.
- **Contract:** the regenerated `spawn_subtask.json`, the prompt section list and the
  public-API snapshots.
- **Manual:** one run with a real model, to show the model now delegates without being
  told an id. This is the user-visible point of issue #34.

The other rows are `n/a`, each with its reason.

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | `build_roster`: sort by id, every rendered field, `(no agents)`, `skills: (none)`, each cap and the `…` marker, `(n more)` skills, the `truncated` report, untrusted wrapping. `clean_field`: controls, newlines, `<`/`>`. `ContextWindowManager.assemble`: `agents` is `STATIC`, never compacted, after `participants`, byte-identical in `instructions()` across two turns. `spawn_subtask`: unknown, empty, known and null `agent`. Default prompt has `## agents` with each R2.1 point; `extends: agents` appends to it. | `uv run pytest tests/unit` |
| T2 | Integration (scenario) | yes | `build_runtime` with a fake A2A card server and a scripted LLM that records its requests, Gherkin-documented: the roster reaches the model, an unknown id is refused with no sub-task, a known id still delegates, the durable engine sends the same `agents` section, the startup log lines. | `uv run pytest tests/integration/agents` |
| T3 | Contract | yes | `docs/a2a/ext/intrinsics/spawn_subtask.json` regenerated with the new `agent` description and pinned. `SECTION_ORDER` gains `agents` and the default prompt matches it. Public-API snapshots (`tiny_harness.harness.agents`, `…core`, `…prompts`) updated deliberately for the new names, and nothing else changes. | `uv run pytest tests/contract` |
| T4 | End-to-end | n/a: the e2e suite drives the web renderer against one harness with no remote agent. T2 covers the whole server-side path (config → card fetch → context → intrinsic → child workflow) in-process. | | |
| T5 | UI / visual | n/a: no renderer, TUI or web change (design § UI/UX design). | | |
| T6 | Snapshot | n/a as its own row: the only snapshots touched are the contract snapshots in T3. | | |
| T7 | Performance / load | n/a: the roster is built once at startup with no I/O, and adds one fixed string per request. The cap bound (design § Security design, about 3.4k characters per agent) is asserted in T8 rather than measured. | | |
| T8 | Security / abuse case | yes | One negative test per abuse case in design § Security design: (1) instruction text in a card lands only inside the untrusted block, after the preamble; (2) a card with `</agents>`, `</untrusted>`, newlines and control characters renders as one single-line entry; (3) a 10 kB description and 50 skills stay within the caps; (4) `spawn_subtask(agent="https://evil.example")` returns `agent.unknown`, no command, and no HTTP request is made. Plus: the roster never contains the agent URL. | `uv run pytest tests/security` |
| T9 | Accessibility | n/a: no user interface changes. | | |
| T10 | Migration / upgrade | n/a: no stored data or config changes. The one behaviour change (an empty `agent` string is now an error, not a local run) is covered by T1 and noted in the PR briefing. | | |
| T11 | Manual exploratory | yes | Two local harnesses with a real model: harness A declares harness B as an agent; a user task that matches B's card is given to A with no agent named. Proves the model now finds and uses the agent by itself (the issue's complaint). | procedure in Verification activities |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1.2, R1.3, R1.4, R4.1 | `build_roster` field, empty-roster and cap cases |
| T1 | R1.1, R1.5, R1.7 | `assemble` section placement, stability, never-compact, byte-identical prefix |
| T1 | R2.1, R2.3 | default prompt `## agents` content; `extends: agents` |
| T1 | R3.1, R3.2, R3.3 | intrinsic unknown / empty / known / null |
| T2 | R1.1, R1.2, R1.6 | `Scenario: The model's context lists a configured remote agent` |
| T2 | R3.1 | `Scenario: A spawn_subtask naming an unknown agent is refused without a sub-task` |
| T2 | R3.2 | `Scenario: A spawn_subtask naming a listed agent still delegates to it` |
| T2 | NFR both engines, R1.5 | `Scenario: The durable engine renders the same agents section on every turn` |
| T2 | R4.2, NFR observability | `Scenario: Startup logs the roster and each truncated card field` |
| T3 | R2.2, R2.3 | `spawn_subtask.json`; `SECTION_ORDER` contract test |
| T8 | Security abuse cases 1–4, R1.3 | `Scenario: A hostile agent card cannot break out of the agents roster` plus the four negative tests |
| T11 | R1, R2 (user value) | real model delegates to the listed agent unprompted |

## Verification environment

- **Repositories:** this repository only.
- **Services / containers:** none for T1, T3 and T8. T2 uses the local Temporal dev
  server that `tests/integration/durable/conftest.py` starts (`start_local`) and the
  in-process A2A server fixture from `tests/integration/a2a/conftest.py` as the fake
  remote agent. Both are started by the tests.
- **Fixtures & data:** the agent cards are built in the tests (benign card and hostile
  card). `FakeLLM` with `scripted` responses
  (`tiny_harness.harness.models.llm`) records every request it receives, so tests read
  the exact `instructions` sent.
- **Credentials:** T1–T8 need none. T11 needs `OPENAI_API_KEY` (by reference; the demo
  README shows how the operator loads it from the secret store).
- **Bring-up:** `uv sync --locked` · **Tear-down:** none (fixtures clean up).
- **T11 procedure:** agent B is a stub A2A agent (about 40 lines on `a2a-sdk`, kept in
  the session scratchpad; its source is copied into the evidence file) on
  `127.0.0.1:8091`. Its card is "Order ledger", with the skill `lookup-order` ("Looks up
  an order's status and refund state by order number"), and it answers each message with
  a fixed status line. A tiny-harness peer cannot be B: its card always has the default
  description and no skills, because nothing in config sets them (a separate gap, out of
  scope here). Harness A is `examples/demo/config.toml` on `127.0.0.1:8090` plus
  `agents = [{ id = "ledger", url = "http://127.0.0.1:8091" }]`. Send A "What is the
  status of order 48213?" through a JSON-RPC `SendMessage`, naming no agent. Start each
  server from a script file and stop it by PID.
- **If bring-up fails:** record it under Verification results, leave the dependent
  activities unticked, and escalate. If `OPENAI_API_KEY` is not available in the
  verification session, T11 is recorded as not executed and raised on the PR. It is
  not ticked.

## Evidence plan

All evidence is committed under `docs/specs/issue-34/evidence/`, redacted (no keys, no
hostnames beyond `127.0.0.1`).

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1 | pytest summary (counts, duration) | `unit.md` |
| T2 | `the-loop scenarios --format markdown` table for `tests/integration/agents` + run summary | `integration.md` |
| T3 | contract run summary + the `spawn_subtask.json` diff | `contract.md` |
| T8 | security run summary, naming each abuse-case test | `security.md` |
| T11 | the rendered `agents` section from A's log, the model's `spawn_subtask` call and the sub-task's result, redacted | `manual-delegation.md` |
| all | full suite as CI runs it (`pre-commit run --all-files`, unit, integration, contract/security/ui) | `ci-parity.md` |

## Verification activities

- [x] T1 — `uv run pytest tests/unit`
- [x] T2 — `uv run pytest tests/integration/agents` and
  `the-loop scenarios --root "$PWD" --glob 'tests/integration/agents/*.py' --format markdown`
- [x] T3 — `uv run pytest tests/contract`
- [x] T8 — `uv run pytest tests/security`
- [x] T11 — the manual procedure in Verification environment, with a real model
- [x] CI parity — `uv run pre-commit run --all-files` and `uv run pytest tests/integration`

## Verification results

All six activities ran and passed. Nothing was skipped.

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| T1 Unit | `uv run pytest tests/unit` | 571 passed | [unit.md](evidence/unit.md) |
| T2 Integration | `uv run pytest tests/integration/agents -v`; `the-loop scenarios … --format markdown` | 20 passed, including the 6 issue-34 scenarios on both engines | [integration.md](evidence/integration.md) |
| T3 Contract | `uv run pytest tests/contract` | 36 passed. `spawn_subtask.json` and the core API snapshot changed on purpose (diffs in the evidence) | [contract.md](evidence/contract.md) |
| T8 Security | `uv run pytest tests/security` | 83 passed. One test per abuse case 1–4, plus the end-to-end hostile-card scenario | [security.md](evidence/security.md) |
| T11 Manual | Two local agents and `gpt-6.1-sol`, per Verification environment | Pass. The model delegated to `ledger` unprompted with a self-contained goal, and answered the user with the agent's result | [manual-delegation.md](evidence/manual-delegation.md) |
| CI parity | `uv run pre-commit run --all-files`; `uv run pytest tests/integration` | All hooks passed; 111 passed | [ci-parity.md](evidence/ci-parity.md) |

**Not executed:** none. In T11, the first attempt failed in the stand-in agent B, not in
tiny-harness. B was fixed and the run repeated (details in the evidence).

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109). Append-only and attributed: an approval never silently
> discards a reviewer's suggestions, and the feedback travels with the document
> it concerns rather than living in a side-channel tracker.

### 2026-10-13 — approved

**@MadaraUchiha-314** wrote:

approved
