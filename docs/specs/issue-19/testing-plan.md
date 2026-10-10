---
type: testing-plan
phase: test-planning
workItem: issue-19
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

# Testing plan: Support connecting to any OpenAI-compatible API

> Derived from the approved [`requirements.md`](requirements.md) and
> [`design.md`](design.md), **before** `tasks.md` — each task's `_Test:_` names a row of
> the matrix below. Authored at the `test-planning` node and **completed at the
> `verification` node**. See `reference/testing.md`.
>
> **This file is executable content.** It names commands an agent will run, so review it
> like code. Credentials appear **by reference only** (env var name, secret-store key),
> never by value.

The proof rests on three layers. **Unit tests** against `httpx.MockTransport` and
recorded bodies prove the configuration rules, the client's wire behaviour and both
API mappings. **An integration scenario** runs a whole task through `build_runtime`
against a scripted OpenAI-compatible server on loopback; run inside a network namespace
with only loopback, it also proves the offline claim without depending on a model's
quality. **An end-to-end run** against a real Ollama shows the demo configuration works
with a real local model.

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | `OpenAIConfig` validators and the `load_settings` secret rule (R1.4, R2, R3.1, R4.3); `OpenAILLM` client construction — URL reached, headers sent, redirects refused, model info (R1.1–R1.3, R1.5, R2.2–R2.3, R4.1–R4.2); Chat Completions request mapping, parsing, streaming assembly and the finish table against recorded bodies (R3.3, R3.4); error translation and parse-failure wrapping on both APIs (R5); the startup log line and chat-span attributes (NFR observability) | `uv run pytest tests/unit` (also the pre-commit hook) |
| T2 | Integration (scenario) | yes | a full task through `running_harness` (embedded Temporal, worker, A2A server — the issue-17 pattern in `tests/integration/embedded/`) whose real `OpenAILLM` is pointed by `[openai] base_url` at a scripted OpenAI-compatible HTTP server on `127.0.0.1`, once per wire API, keyless; Gherkin-documented (R1.1, R2.2, R3.2, R3.3, R5.1) | `uv run pytest tests/integration/compat` (in CI's `uv run pytest tests/integration`) |
| T3 | Contract (OpenAPI / GraphQL SDL) | n/a — no HTTP API the harness serves changes; the A2A surface and agent card are untouched. The outbound OpenAI wire formats are pinned by T1's recorded fixtures instead | | |
| T4 | End-to-end | yes | the demo with `examples/demo/config.ollama.toml` against a real Ollama, no `OPENAI_API_KEY` and no `TEMPORAL_API_KEY`, takes the demo complaint to a terminal task state (R6.1, R6.2) | `uv run pytest tests/e2e -k ollama` (marked `e2e`; skips with a reason when no Ollama answers on `127.0.0.1:11434` or the model is not pulled) |
| T5 | UI / visual | n/a — no rendered state changes (design § UI/UX: N/A); the existing `tests/ui` suite runs as regression in T10 | | |
| T6 | Snapshot | yes | the public API snapshots under `tests/contract/snapshots/` (`settings.schema.json`, `tiny_harness.config.txt`, `tiny_harness.harness.models.txt`, `tiny_harness.harness.core.txt`) change only additively; the regenerated diff is reviewed in the PR | `uv run pytest tests/contract` |
| T7 | Performance / load | n/a — no hot path changes: the adapter adds one dispatch per model call, and a local model's latency is the server's, not the harness's. The demo's longer `timeout` is a configuration value, verified in T4 | | |
| T8 | Security / abuse case | yes | one negative test per row of design § Security design's abuse-case table (abuse cases 1–5) plus the organization/project header suppression and the redirect refusal; plus the offline proof: T2's scenario re-run inside `unshare -rn` with only loopback up | `uv run pytest tests/unit tests/integration/compat -k "abuse or security"`; offline procedure under Verification activities |
| T9 | Accessibility | n/a — no user interface is added or changed | | |
| T10 | Migration / regression | yes | every existing configuration keeps working with none of the new keys (NFR backwards compatibility): `examples/demo/config.toml` and `config.embedded.toml` load unchanged and still require `OPENAI_API_KEY`; the existing Responses request-mapping test passes unedited; the full suite passes | `uv run pre-commit run --all-files` and `uv run pytest tests/integration tests/contract tests/security tests/ui` (CI's exact commands) |
| T11 | Manual exploratory | yes | `tiny-harness tui` hosting its own harness with the Ollama configuration: one message sent and answered, then quit; read the startup log line for the endpoint and API | procedure under Verification activities |
| T12 | Documentation | yes | README, getting-started guide, configuration and models capability docs describe the new keys and the offline run (R6.3); the docs site builds | `bun run --cwd docs docs:build`; markdownlint via pre-commit |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1.1 | `base_url = http://127.0.0.1:<p>/v1` → the request URL is `http://127.0.0.1:<p>/v1/responses` (and `/chat/completions`) |
| T1 | R1.2 | no `base_url` → the request reaches `https://api.openai.com/v1/responses` |
| T1 | R1.4 | `base_url` = `ftp://h/v1`, `127.0.0.1:11434/v1`, `not a url` → `ConfigError(openai.base_url)` |
| T1 | R1.5 | `model = "openai/gpt-oss-120b"` and `"qwen3:8b"` → sent verbatim |
| T1 | R2.1 | no `base_url`, no key → `ConfigError(OPENAI_API_KEY)` (unchanged) |
| T1 | R2.2 | `base_url` set, no key → settings load; the request carries no `Authorization` header |
| T1 | R2.3 | `base_url` set, key set → `Authorization: Bearer <key>` |
| T1 | R2 backstop | `OpenAIConfig()` with neither key nor `base_url` → validation error |
| T1 | R3.1 | `api` absent → `responses`; `api = "chat"` → `ConfigError(openai.api)` |
| T1 | R3.3 | chat mapping: system first; user/assistant turns; consecutive tool calls grouped into one assistant message; tool results as `tool` messages; tools and `response_format` shape; `max_tokens`; no `store` / `prompt_cache_key` |
| T1 | R3.3 | chat parsing (recorded bodies): text; tool calls decoded through wire names; refusal; `content_filter`; `length`; cached tokens |
| T1 | R3.3 | chat streaming (recorded SSE): text deltas in order; fragmented tool-call arguments assembled; usage chunk; `done` response equals the non-streamed parse |
| T1 | R3.4 | chat body with no `usage`, no `id` on a tool call → zeros and `call_<index>`, no failure |
| T1 | R4.1–R4.3 | `context_window_tokens = 16384` → `info.context_window_tokens == 16384`; unset → table / 400 000; `0` and `-1` → `ConfigError(openai.context_window_tokens)` |
| T1 | R5.1–R5.2 | 429, 503, timeout, connection refused → `RetryableProviderError`; 400, 404 → `ProviderError(status)`; both APIs |
| T1 | R5.3 | empty `choices`, wrong-typed fields, invalid tool-call JSON, on invoke and stream, both APIs → `ProviderError(status=200)` |
| T1 | NFR obs. | startup log line `model endpoint http://127.0.0.1:11434 api=chat_completions model=…`, no path, query or key; chat span carries `server.address`, `server.port`, `tiny_harness.llm.api` |
| T2 | R1.1, R2.2, R3.2 | `Scenario: Harness completes a task against an OpenAI-compatible Responses endpoint` |
| T2 | R1.1, R2.2, R3.3 | `Scenario: Harness completes a task against an OpenAI-compatible Chat Completions endpoint` |
| T2 | R5.1 | `Scenario: A retryable endpoint failure is retried and the task completes` |
| T4 | R6.1, R6.2 | `Scenario: Demo completes a task offline against a local Ollama` |
| T6 | NFR compat. | additive diff only in the four snapshots |
| T8 | abuse 1 | `OPENAI_BASE_URL=http://evil.invalid/v1` in the environment → requests still reach the configured host, and the default host when none is configured |
| T8 | abuse 2 | `http://10.0.0.5/v1` + key → `ConfigError(openai.base_url)`; `http://127.0.0.1/v1`, `http://[::1]/v1`, `http://localhost/v1` + key → accepted; `http://10.0.0.5/v1` without key → accepted; `http://localhost.evil.invalid/v1` + key → refused |
| T8 | abuse 3 | `http://u:p@127.0.0.1/v1`, `https://u@h/v1` → `ConfigError(openai.base_url)` |
| T8 | abuse 4 | malformed bodies (T1 R5.3 cases) never escape as an unhandled exception |
| T8 | abuse 5 | with a key configured: the key appears in neither the startup log, a translated error, nor a span |
| T8 | design § headers | `OPENAI_ORG_ID` / `OPENAI_PROJECT_ID` set + `base_url` → neither header sent; no `base_url` → today's behaviour |
| T8 | R1.1 / design § redirects | the endpoint answers `307` to another host → `ProviderError`, and the other host receives nothing |
| T8 | R6.2 offline | T2's scenarios pass inside `unshare -rn` with only `lo` up |
| T10 | NFR compat. | existing configs load; existing suites green |
| T11 | R6, NFR obs. | manual TUI walkthrough |
| T12 | R6.3 | doc sections present; site builds |

## Verification environment

- **Repositories:** this repository only, at the head of `loop/issue-19`.
- **Services:**
  - T2, T8: none to start by hand — each test starts its scripted OpenAI-compatible
    server (a `starlette` app under `uvicorn`, both already in the dev environment — no
    new dependency) on an OS-chosen loopback port, and an embedded Temporal from the
    binary already cached in `~/.cache/temporalio`.
  - T4, T11: a local **Ollama**. It is not installed on the verification machine today;
    bring-up installs it into a user-local directory and pulls a model sized for the
    machine (4 CPUs, 7 GB RAM, no GPU): **`qwen3:1.7b`**, selected for the run with the
    test's `TINY_HARNESS_OLLAMA_MODEL` override, since the demo configuration's
    `qwen3:8b` does not fit this hardware. The embedded Temporal CLI is already cached in
    `~/.cache/temporalio`.
- **Network:** bring-up needs outbound HTTPS once (the Ollama release and the model).
  T2, T8 and T4's run itself need none; the offline activity removes the network
  entirely.
- **Fixtures & data:** recorded Chat Completions bodies and SSE streams under
  `tests/fixtures/openai/chat/` (hand-written to the published wire format and checked
  against Ollama's real output during T4 bring-up); each T2 test uses a `tmp_path` store
  and a unique task queue; the scripted server answers with recorded bodies in the order the scenario scripts.
- **Credentials:** **by reference only.**
  - T1, T2, T4, T8, T11: **none** — `OPENAI_API_KEY` and `TEMPORAL_API_KEY` MUST be unset
    (`env -u OPENAI_API_KEY -u TEMPORAL_API_KEY …`), which is part of the proof.
    `TINY_HARNESS_PUSH_KEY` is generated per run (`openssl rand -base64 32`).
  - T10: CI's existing secrets only; nothing new.
- **Bring-up:**
  - Python: `uv sync --locked`.
  - Ollama (T4, T11): download the Linux release archive from Ollama's GitHub releases
    into `~/.local/opt/ollama`, then
    `OLLAMA_CONTEXT_LENGTH=16384 ~/.local/opt/ollama/bin/ollama serve &` and
    `~/.local/opt/ollama/bin/ollama pull qwen3:1.7b`.
  - Docs (T12): `bun install --cwd docs --frozen-lockfile`.
- **Tear-down:** stop `ollama serve` by its PID (never `pkill -f`); tests stop their own
  servers.
- **If bring-up fails** (Ollama will not install or the model will not run on this
  machine): record it under Verification results, leave T4 and T11 unticked, and
  escalate on the PR. T2 inside the namespace still proves the offline claim; T4 is the
  only proof that a *real* local model works, so it is not silently dropped.

## Evidence plan

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1 | test summary (counts, duration) and the new test ids | `unit.md` |
| T2 | scenario table (`the-loop scenarios --format markdown`) and run output | `integration.md` |
| T4 | the run's transcript and final task, server log excerpt showing the endpoint line; model and Ollama version | `e2e-ollama.md` |
| T6 | the snapshot diff | `contract.md` |
| T8 | negative-test output; the offline run's `ip -brief addr` inside the namespace and its pytest output | `security.md` |
| T10 | pre-commit and CI-command output | `regression.md` |
| T11 | the walkthrough's steps, the log line, a terminal screenshot of the answered message | `manual.md`, `manual/tui.png` |
| T12 | docs build output and the list of pages touched | `documentation.md` |

Redact before committing: local paths under the home directory, host names other than
`127.0.0.1`/`localhost`, and any key-shaped string.

## Verification activities

- [ ] T1 — `uv run pytest tests/unit`
- [ ] T2 — `uv run pytest tests/integration/compat`
- [ ] T4 — with Ollama up and `qwen3:1.7b` pulled: `env -u OPENAI_API_KEY -u TEMPORAL_API_KEY TINY_HARNESS_OLLAMA_MODEL=qwen3:1.7b uv run pytest tests/e2e -k ollama -s`
- [ ] T6 — `uv run pytest tests/contract`, then `git diff tests/contract/snapshots`
- [ ] T8 — `uv run pytest tests/unit tests/integration/compat -k "abuse or security"`
- [ ] T8 offline — `unshare -rn sh -c 'ip link set lo up && ip -brief addr && env -u OPENAI_API_KEY -u TEMPORAL_API_KEY .venv/bin/pytest tests/integration/compat'`
- [ ] T10 — `uv run pre-commit run --all-files` and `uv run pytest tests/integration tests/contract tests/security tests/ui`
- [ ] T11 — with Ollama up: `env -u OPENAI_API_KEY -u TEMPORAL_API_KEY uv run tiny-harness --config <copy of config.ollama.toml with model qwen3:1.7b> tui`; send "hello", wait for the answer, quit; read `tiny-harness.log` for the `model endpoint` line
- [ ] T12 — `bun run --cwd docs docs:build`

## Verification results

*Not yet executed.*

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| | | | |

**Not executed:** none yet.

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109). Append-only and attributed: an approval never silently
> discards a reviewer's suggestions, and the feedback travels with the document
> it concerns rather than living in a side-channel tracker.
