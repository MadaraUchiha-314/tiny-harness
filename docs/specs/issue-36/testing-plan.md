---
type: testing-plan
phase: test-planning
workItem: issue-36
status: approved
approvedBy: ["MadaraUchiha-314"]
overrides: {}
---

<!-- Written per the `the-loop:writing` skill: front-load each section's
     conclusion, draw it rather than describe it (3+ named parts -> a mermaid
     diagram), and keep the formal registers formal (EARS, abuse cases,
     RFC-2119, API contracts, schema descriptions). -->

# Testing plan: mount tiny-harness agents onto an existing FastAPI or Starlette app

> Derived from [`requirements.md`](requirements.md) and [`design.md`](design.md), before
> `tasks.md`. Authored at `test-planning`, completed at `verification`.
>
> **This file is executable content.** It names commands an agent will run; review it
> like code. No credential is needed. Every test runs offline over a scripted model
> (`tiny_harness.harness.models.scripted`) and a local Temporal dev server
> (`start_local`, as since PR #28).

The work is proved in six layers:

| Layer | What it covers |
|-------|----------------|
| **Unit** | The pure pieces: `public_url`, `Claims`, `TemporalPool`, `RouteOptions`, the resolver, ownership with a fake client, `SecretRegistry`, `AgentConfig` |
| **Integration** | Harnesses mounted in real host apps, served by a real uvicorn server on an ephemeral loopback port, so agent-to-agent calls and pushes travel real HTTP |
| **Acceptance** | The issue author's test: five agents in one app, delegating to each other |
| **Security** | One negative test per abuse case in `design.md` § Security design |
| **Contract** | The settings schema, the public-API snapshots and the unchanged agent card |
| **Static** | ruff, pyright strict and markdownlint, as CI |

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | `public_url` (every row of the design's table, normalization, the mismatch error); `Claims` (each clash, release, resolved store paths, thread safety); `TemporalPool` reference counts and keys (no API key in the key); `RouteOptions` toggles (which routes and middleware exist); `HarnessContextBuilder` with and without a resolver, resolver raising; strict `sender_of`; `TemporalTaskStore` and `PushReceiver` ownership over a fake client (owned, foreign, `describe` failing, LRU hit); `SecretRegistry` versioning in `Redactor`; `schedule_id`; `AgentConfig` and `effective_task_queue` defaults; the `ListTasks` `context_id` escaping; `Harness` lifecycle errors (second start, start after stop, `client` before start) | `uv run pytest tests/unit` |
| T2 | Integration (scenario) | yes | Over the local Temporal dev server, Gherkin-documented: one harness mounted under a prefix in a host Starlette app; the 503 window before start; the wrong-mount refusal; the card's prefixed URLs; the top-level `HarnessApp` lifespan; the FastAPI router (lifespan merge, OpenAPI tags and paths, 503 and limits dependencies, include-prefix refusal); the push route off ⇒ follow; `harnesses_lifespan` starting and stopping in order; a part-way start failure undoing what ran; a client passed in and not closed; the agent id on log lines | `uv run pytest tests/integration/mount` |
| T3 | Acceptance (scenario) | yes | `examples/multi_agent/`: five configurations, one Starlette app (and its FastAPI variant), one shared embedded dev server. Agent `a` delegates to `b` over HTTP and gets the result; `b` parks and its push reaches `a`'s prefixed route; `b` delegates on to `d`. All five cards resolve at their prefixes | `uv run pytest tests/integration/mount/test_multi_agent.py` |
| T4 | Security / abuse case | yes | Abuse cases 1–6 of `design.md`: header ignored with a resolver, and a message's self-claim refused in strict mode; every task operation of agent b refused on agent a (GetTask, ListTasks, CancelTask, SubscribeToTask, four push-config operations, SendMessage with b's id), with b's task unchanged; b's stand-in pushed at a's route → `401`, not woken; shared namespace and queue → `HarnessConflictError`, no worker polled; a request before start → `503`, no Temporal call; agent b's key in agent a's log line → masked | `uv run pytest tests/security/test_multi_agent_isolation.py tests/security/test_participant_resolver.py` |
| T5 | Contract | yes | `settings.schema.json` gains `[agent]` and an optional `task_queue`. The public-API snapshots of `tiny_harness.service`, `tiny_harness.config` and `tiny_harness.errors` gain `Harness`, `harnesses_lifespan`, `RouteOptions`, `AgentConfig` and the new errors, and nothing else changes. `agent-card.json` is **unchanged** (R7.3). A new snapshot covers `tiny_harness.fastapi` | `uv run pytest tests/contract` |
| T6 | Back compatibility (regression) | yes | R7: the whole existing suite passes **unmodified** on the rebuilt `running_harness` and `serve`, except for tests that import the removed `runtime.AGENT_ID`. Each such edit is listed in the evidence with its reason. A configuration file from `examples/demo/` loads with id and queue `tiny-harness`, and the default heartbeat schedule id is still `tiny-harness-heartbeat` | `uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui` |
| T7 | Packaging | yes | The built wheel installs without FastAPI, and `import tiny_harness.fastapi` raises the `ImportError` naming the extra (R3.4). With `tiny_harness[fastapi]`, the router imports. Extends `tests/integration/test_package.py` | `uv run pytest tests/integration/test_package.py` |
| T8 | End-to-end | n/a: the e2e suite runs the demo against Temporal Cloud and OpenAI with one agent. T3 runs the whole multi-agent path over real HTTP and a real Temporal server; a live model adds nothing to what is proved here. | | |
| T9 | UI / visual | n/a: no renderer or TUI change (design § UI/UX: N/A). | | |
| T10 | Snapshot | n/a beyond T5: no rendered output changes. | | |
| T11 | Performance / load | yes (narrow) | NFR startup and overhead: five harnesses sharing a pool open **one** Temporal connection (counted by the pool and asserted in T3); a known task id's ownership check makes no second `describe` (LRU, asserted in T1). No timing benchmark: the 503 gate is one boolean read | (asserted inside T1, T3) |
| T12 | Accessibility | n/a: no user interface. | | |
| T13 | Migration / upgrade | yes (narrow) | Covered by T6: an existing configuration without `[agent]` or with an explicit `task_queue` keeps today's id, queue and schedule id. No store schema or workflow signature changes, so there is no data migration and no replay risk | (inside T6) |
| T14 | Manual exploratory | yes | Run `examples/multi_agent/` by hand per its README with `tiny-harness tui --url http://127.0.0.1:8090/agents/a` and a scripted or real model; open the FastAPI variant's `/docs` and check the five tagged groups. Confirms that the README steps work as written | manual, per `examples/multi_agent/README.md` |
| T15 | Docs build | yes | The new and changed pages (`docs/sdk/mount.md`, `docs/configuration/agent.md`, the deploy guide, capability docs) build and pass markdownlint | `cd docs && bun run docs:build` |
| T16 | Static | yes | ruff, pyright strict (including `tiny_harness/fastapi.py` with FastAPI installed in the dev group), markdownlint over all files, as CI | `uv run pre-commit run --all-files` |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R2.4 | `public_url` table and mismatch `ConfigError` |
| T1 | R5.3, R5.8 | `Claims` refuses a duplicate id, namespace+queue, store path |
| T1 | R5.2, NFR | `TemporalPool` shares one client per key; the key holds no API key |
| T1 | R4.1–4.3 | resolver used, header ignored, `None` ⇒ no participant, raise ⇒ error |
| T1 | R4.6, R7.2 | `AgentConfig` defaults; queue defaults to the agent id |
| T2 | R1.1–1.5 | `Scenario: A harness starts from a host lifespan and opens no port` |
| T2 | R1.3 | `Scenario: A Temporal client passed in is used and not closed` |
| T2 | R2.1, R2.3 | `Scenario: An agent mounted under a prefix serves its card with prefixed URLs` |
| T2 | R2.2 | `Scenario: A mounted agent answers 503 until its harness has started` |
| T2 | R2.4, design § mount check | `Scenario: An agent mounted at the wrong path refuses every request` |
| T2 | R2.5, R7.1 | `Scenario: A top-level harness app starts itself from the server lifespan` |
| T2 | R3.1–3.3 | `Scenario: A FastAPI app includes an agent router and lists its routes in OpenAPI` |
| T2 | R3.2 | `Scenario: A router included under another prefix refuses every request` |
| T2 | R4.4 | `Scenario: Limits and CORS can each be turned off` |
| T2 | R4.5 | `Scenario: With the push route off a remote sub-task is followed` |
| T2 | R5.1 | `Scenario: Several harnesses start and stop in order from one lifespan` |
| T2 | NFR observability | `Scenario: Each log line names the agent that wrote it` |
| T3 | R5.1–5.7, R6.1–6.4, NFR startup | `Scenario: five agents in one app delegate to each other` |
| T3 | R6.2 | `Scenario: A parked sub-task on agent b pushes to agent a's prefixed route` |
| T3 | R3, R6 | `Scenario: five agents in one FastAPI app delegate to each other` |
| T4 | abuse 1 | `Scenario: With a resolver a spoofed participant header is ignored` |
| T4 | abuse 2, R5.4 | `Scenario: Agent a treats every task of agent b as unknown` |
| T4 | abuse 3 | `Scenario: A push for agent b's stand-in at agent a's route is refused` |
| T4 | abuse 4, R5.3 | `Scenario: A second harness on the same namespace and queue does not start` |
| T4 | abuse 5 | `Scenario: A request before start never reaches Temporal` |
| T4 | abuse 6 | `Scenario: One agent's log masks another agent's key` |
| T5 | R3.4, R4.6, R7.3 | snapshots: schema, public API, unchanged card |
| T6 | R7.1–7.3 | existing suite unmodified |
| T7 | R3.4 | wheel without the extra; with the extra |
| T14 | R8.1 | README walkthrough |
| T15 | R8.1–8.4 | docs build |

## Verification environment

- **Repositories:** this repository only, branch `loop/issue-36`.
- **Services:** the Temporal dev server, started by the tests through `start_local`
  (downloaded once into the uv cache). Nothing else to bring up.
- **HTTP:** T2 and T3 serve the host app with uvicorn on `127.0.0.1` and an ephemeral
  port chosen by the OS. Agents reach each other and push to each other over that real
  loopback socket. `httpx.ASGITransport` is not used where a stream must stay open,
  because it buffers server-sent events.
- **Fixtures & data:** scripted models (`tiny_harness.harness.models.scripted`) per
  agent; temporary directories for each agent's store and the shared embedded Temporal
  database; the five `examples/multi_agent/*.toml` files, with `base_url` and paths
  rewritten for the test's port and temporary directory.
- **Credentials:** none. `OPENAI_API_KEY` is only for the optional manual run in T14,
  by reference, and is never written down.
- **Bring-up:** `uv sync --locked` (the dev group includes FastAPI).
- **Tear-down:** none. pytest's `tmp_path` and the tests' context managers stop every
  server and remove every file.
- **Temp space:** if `/tmp` is full, set `TMPDIR` to a directory under `~/.cache` before
  running.
- **If bring-up fails** (the dev server cannot download or start): record it under
  Verification results, leave T2–T4 and T6 unticked, and escalate on PR #37.

## Evidence plan

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1 | test summary (counts, duration) | `unit.md` |
| T2, T3 | `the-loop scenarios --root "$PWD" --format markdown` table for the new scenarios, plus run output | `integration.md` |
| T3 | the run log of the five-agent scenario, showing a's delegation to b, b's push to `/agents/a/a2a/push/…`, and one pool connection | `acceptance.md` |
| T4 | run output, one line per abuse case | `security.md` |
| T5 | snapshot diff (schema, public API) and the unchanged card | `contract.md` |
| T6 | full-suite summary, and the list of edited existing tests with reasons | `regression.md` |
| T7 | package test output | `packaging.md` |
| T14 | the manual walkthrough steps and outcomes; a redacted screenshot of the FastAPI `/docs` page with the five groups | `manual.md`, `manual/openapi-docs.png` |
| T15, T16 | build and pre-commit output | `static.md` |

All output is redacted before it is committed. It is loopback-only, but it still gets
checked for tokens and home paths.

## Verification activities

- [x] T1 — `uv run pytest tests/unit`
- [x] T2 — `uv run pytest tests/integration/mount`
- [x] T3 — `uv run pytest tests/integration/mount/test_multi_agent.py`
- [x] T4 — `uv run pytest tests/security/test_multi_agent_isolation.py tests/security/test_participant_resolver.py`
- [x] T5 — `uv run pytest tests/contract`
- [x] T6 — `uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui`
- [x] T7 — `uv run pytest tests/integration/test_package.py`
- [x] T14 — manual walkthrough of `examples/multi_agent/README.md`, and the FastAPI `/docs` check
- [x] T15 — `cd docs && bun run docs:build`
- [x] T16 — `uv run pre-commit run --all-files`

## Verification results

Executed on 2026-10-13 against branch `loop/issue-36`. Every planned activity ran, and
all pass.

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| T1 Unit | `uv run pytest tests/unit` | 632 passed. A mutation check confirms the ownership test fails without the queue check | [unit.md](evidence/unit.md) |
| T2 Integration | `uv run pytest tests/integration/mount` | 14 passed (8 Starlette, 3 FastAPI, 3 five-agent) | [integration.md](evidence/integration.md) |
| T3 Acceptance | `uv run pytest tests/integration/mount/test_multi_agent.py` | 3 passed: five agents delegating over HTTP in Starlette and FastAPI, a push to a's prefixed route, one pool connection | [acceptance.md](evidence/acceptance.md) |
| T4 Security | `uv run pytest tests/security/test_multi_agent_isolation.py tests/security/test_participant_resolver.py` | 6 passed, one per abuse case 1–6 | [security.md](evidence/security.md) |
| T5 Contract | `uv run pytest tests/contract` | 37 passed. Snapshots changed on purpose, agent card unchanged | [contract.md](evidence/contract.md) |
| T6 Regression | `uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui` | 902 passed (after fixing two bugs in the new tests, see evidence). One existing fixture moved its monkeypatch to the new seam | [regression.md](evidence/regression.md) |
| T7 Packaging | `uv run pytest tests/integration/test_package.py` | 2 passed. Without the extra, the import names `tiny_harness[fastapi]` | [packaging.md](evidence/packaging.md) |
| T11 Performance (narrow) | Asserted inside T1 (LRU: a known id is described once) and T3 (`open_connections() == 1`) | Pass | [unit.md](evidence/unit.md), [acceptance.md](evidence/acceptance.md) |
| T13 Migration (narrow) | Inside T6 and T1 (`test_the_demo_configuration_loads_unchanged`, `test_no_agent_section_keeps_todays_id_and_queue`, default schedule id) | Pass | [regression.md](evidence/regression.md) |
| T14 Manual | `examples/multi_agent` FastAPI variant with a real model | Pass, with two findings: the README did not say to unset `TEMPORAL_API_KEY` (fixed), and without naming the agent the model does not delegate, because remote agents are not in the system prompt (issue-34's scope) | [manual.md](evidence/manual.md), [screenshot](evidence/manual/openapi-docs.png) |
| T15 Docs build | `cd docs && bun run docs:build` | Build complete | [static.md](evidence/static.md) |
| T16 Static | `uv run pre-commit run --all-files` | All hooks pass | [static.md](evidence/static.md) |

**Not executed:** none.

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109). Append-only and attributed: an approval never silently
> discards a reviewer's suggestions, and the feedback travels with the document
> it concerns rather than living in a side-channel tracker.

### 2026-10-13 — approved

**@MadaraUchiha-314** wrote:

approved
