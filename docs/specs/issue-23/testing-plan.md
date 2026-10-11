---
type: testing-plan
phase: test-planning
workItem: issue-23
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

# Testing plan: Remove `TINY_HARNESS_PUSH_KEY` from the end-to-end architecture

> Derived from [requirements.md](requirements.md) and [design.md](design.md), before
> `tasks.md`. Completed at the `verification` node. Reviewed on PR #24 (the
> `design-approval` gate was skipped by declaration).
>
> **This file is executable content.** Credentials appear by reference only.

Six rows carry the proof: unit, integration, contract snapshots, security, an
end-to-end demo against the local Ollama with the variable absent, and a migration
check for rows an earlier version wrote. The rest are `n/a` with a reason.

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | settings load with the variable unset and set; the ignored-variable warning; `PushConfigRecord` JSON round-trip, masking and legacy detection; `SqliteStore` creates a new file `0600`; `secret_values` | `uv run pytest tests/unit` |
| T2 | Integration (scenario) | yes | A2A push config round-trips `token`/`authentication` and reaches the webhook with the token header; get/list/delete; the embedded CLI `serve` starts without the variable | `uv run pytest tests/integration` |
| T3 | Contract (snapshot of public API and settings schema) | yes | `push_key` gone from the settings schema and `Settings`; `PushTokenCipher` gone and `PushConfigRecord`'s new fields in the persistence API; no other snapshot changes | `uv run pytest tests/contract` |
| T4 | End-to-end | yes | the Ollama demo (embedded Temporal, loopback Ollama) completes a task with `TINY_HARNESS_PUSH_KEY` absent from every process's environment | `TINY_HARNESS_OLLAMA_MODEL=qwen3:1.7b uv run pytest tests/e2e/test_demo_ollama.py -s -rs` |
| T5 | UI / visual | n/a — no renderer or UI changes; the web renderer never saw the key | | |
| T6 | Snapshot | covered by T3 — the project's snapshots are its contract tests | | |
| T7 | Performance / load | n/a — removing an AES-GCM call per push-config read/write has no measurable cost to prove | | |
| T8 | Security / abuse case | yes | abuse cases 1–4 of requirements.md: file mode `0600`; credential masked in `repr`/logs and absent from the warning lines; the ignored variable's value never logged; a legacy row is never sent to the webhook | `uv run pytest tests/security` |
| T9 | Accessibility | n/a — no user interface | | |
| T10 | Migration / upgrade | yes | a store holding a push config written in the 0.5.x shape (`token_ciphertext` set): it is not listed, not delivered, deleted, and a warning names task and config id | in T2 (`tests/integration/a2a/test_server.py`) and T1 |
| T11 | Manual exploratory | yes | `tiny-harness serve` with the variable set logs the "set and ignored" warning once and does not echo the value; a new SQLite file's mode | a scripted run, below |
| T12 | Full repository checks | yes | lint, format, type check and unit tests across every file, as CI runs them | `uv run pre-commit run --all-files` |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1.1, R1.2 | settings load from an environment with no `TINY_HARNESS_PUSH_KEY`; `Settings` has no `push_key` |
| T1 | R1.3 | `ignored_environment_warnings` returns the push-key line when set, nothing when unset or empty; `OPENAI_BASE_URL` line unchanged |
| T1 | R2.1, R3.1 | `PushConfigRecord` JSON round-trip keeps `token`/`authentication`; stored JSON has them as supplied, no ciphertext keys |
| T1 | R4.1 | a record validated from 0.5.x-shaped JSON has `legacy == True`; one with neither ciphertext field does not |
| T1 | R3.2 | `SqliteStore(tmp/new.sqlite3)` leaves the file at mode `0600`; an existing file's mode is unchanged |
| T2 | R2.1, R2.2 | `Scenario: push notification configs receive status updates` (rewritten: token reaches the webhook; stored token equals the supplied one) |
| T2 | R2.1, R2.3 | `Scenario: a push config's credentials round-trip through get, list and delete` |
| T2, T10 | R4.1, R4.2 | `Scenario: a push config stored encrypted by an earlier version is dropped, not delivered` |
| T2 | R1.2, R5.3 | `Scenario: serve starts in embedded mode` (existing CLI test) runs with no `TINY_HARNESS_PUSH_KEY` |
| T3 | R1.4 | settings schema snapshot diff: `push_key` removed from `properties` and `required` |
| T4 | R1.2, R5.3 | the Ollama demo completes a task; the demo's environment has no `TINY_HARNESS_PUSH_KEY` |
| T8 | abuse 1 | new SQLite file mode `0600` |
| T8 | abuse 2 | `repr(record)`, `str(record)`, `record.model_dump()` contain no credential; the legacy-drop warning carries no ciphertext |
| T8 | abuse 3 | warning line for a set `TINY_HARNESS_PUSH_KEY` does not contain its value |
| T8 | abuse 4 | the sender's config list for a task with a legacy row is empty |
| T11 | R1.3, R3.2 | scripted run, see activities |
| — | R4.3, R5.1, R5.2, R5.4 | documentation and dependency checks: `grep -rn TINY_HARNESS_PUSH_KEY README.md docs/guide docs/capabilities examples tests tiny_harness` returns nothing outside the historic-spec and upgrade-note lines; `grep -rn cryptography pyproject.toml tiny_harness` returns nothing |

## Verification environment

- **Repositories:** this repository only, at the PR branch `loop/issue-23`.
- **Services:** the integration tests start Temporal's test server themselves. T4 and
  T11 use an embedded Temporal (the cached CLI under the project's download dir). T4
  needs a local Ollama answering on `127.0.0.1:11434` with `qwen3:1.7b` pulled; the
  machine has one.
- **Fixtures & data:** a 0.5.x-shaped `push_configs` row is written directly through
  `SqliteStore.put` of a record carrying `token_ciphertext` (or by raw insert of the
  old JSON) — no old binary is needed.
- **Credentials:** none. T4 runs with no `OPENAI_API_KEY`, `TEMPORAL_API_KEY` or
  `TINY_HARNESS_PUSH_KEY`. T11 sets `TINY_HARNESS_PUSH_KEY` to a value generated per
  run (`openssl rand -base64 32`) and `OPENAI_API_KEY=sk-unused`; neither is recorded.
- **Bring-up:** `uv sync --locked`. **Tear-down:** the tests stop what they start; T11's
  script kills its server by PID.
- **If bring-up fails:** record it below, leave the dependent activity unticked, and
  escalate on the PR.

## Evidence plan

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1 | test summary | `unit.md` |
| T2, T10 | scenario table (`the-loop scenarios`) and run output | `integration.md` |
| T3 | snapshot diff and run output | `contract.md` |
| T4 | run output, the demo environment's variable list (names only) | `e2e-ollama.md` |
| T8 | run output | `security.md` |
| T11 | the command, the warning line, `stat` of the new file | `manual.md` |
| T12 | hook output | `regression.md` |
| docs/deps | the grep commands and their output | `documentation.md` |

Redaction: generated keys and any path under the home directory are replaced before
committing.

## Verification activities

- [ ] T1 — `uv run pytest tests/unit`
- [ ] T2 / T10 — `uv run pytest tests/integration`
- [ ] T3 — `uv run pytest tests/contract`
- [ ] T4 — `TINY_HARNESS_OLLAMA_MODEL=qwen3:1.7b uv run pytest tests/e2e/test_demo_ollama.py -s -rs` with `TINY_HARNESS_PUSH_KEY` unset
- [ ] T8 — `uv run pytest tests/security`
- [ ] T11 — embedded `tiny-harness serve` with `TINY_HARNESS_PUSH_KEY` set, a fresh `[store] sqlite_path`; capture the warning and `stat -c %a` of the new file
- [ ] T12 — `uv run pre-commit run --all-files`
- [ ] docs/deps — the two `grep` checks of the trace table

## Verification results

_Not yet executed._

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| | | | |

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109).
