---
type: evidence
workItem: issue-36
---

# Final validation: mount tiny-harness agents onto an existing FastAPI or Starlette app

> Summarised from `testing-plan.md` § Verification results, plus the full-suite runs
> after the review fixes. The last run on the reviewed head: 975 passed (before the two
> critic fixes, which added unit tests). Raw evidence is beside this file.

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| R1 Start a harness without a server | `Harness` started from a host lifespan, with no port on `[server] bind`. A client passed in is used and not closed. Lifecycle errors and a part-way failure undo what was done | [integration.md](integration.md) (`test_starlette.py`), [unit.md](unit.md) (`test_harness_lifecycle.py`) |
| R2 Mount on Starlette | Card URLs carry the prefix. 503 before start. A wrong or inexact mount gives 500. The top-level app starts from the lifespan. Prefix and `base_url` disagreement is a `ConfigError` | [integration.md](integration.md), [unit.md](unit.md) (`test_public_url.py`, `test_harness_app.py`) |
| R3 FastAPI router | Lifespan merged. Routes in OpenAPI per agent: five groups, 16 routes each, in the manual run. 503 and limits as dependencies. An extra include prefix or `root_path` is refused. Without the extra, the import names `tiny_harness[fastapi]` | [integration.md](integration.md) (`test_fastapi.py`), [packaging.md](packaging.md), [manual.md](manual.md), [screenshot](manual/openapi-docs.png) |
| R4 Customize | Participant resolver with strict mode. Limits, CORS, monitor, push and ui switches. `[agent] id`; the card's name and description come from issue-34's `[card]` | [security.md](security.md) (abuse case 1), [unit.md](unit.md) (`test_context_builder.py`, `test_harness_app.py`, `test_config_agent.py`) |
| R5 Several isolated agents | Claims refuse a shared id, queue, store or public URL. Ownership by queue for every task operation and the push route. One pool connection for five agents. Per-agent heartbeat and plugin data. Agent id on log lines | [security.md](security.md) (abuse cases 2–6), [acceptance.md](acceptance.md), [unit.md](unit.md) (`test_pool.py`, `test_claims.py`, `test_heartbeat_id.py`) |
| R6 Agents delegate to each other | Five example configurations in one app (Starlette and FastAPI): a → b → d over HTTP. b's push reaches a's prefixed route. Same-process peers get cards built from their settings. Manual run with a real model: a delegated to b through the same app | [acceptance.md](acceptance.md), [manual.md](manual.md) |
| R7 Existing entry points unchanged | The whole existing suite passes. The one fixture edit is listed with its reason. The agent card is byte-identical to `main`. The default agent keeps its id, queue, schedule and plugin-data folder | [regression.md](regression.md), [contract.md](contract.md) |
| R8 Documentation | `docs/sdk/mount.md`, `docs/configuration/agent.md`, deploy, server and temporal pages, capability docs and decision-009. The docs build passes | [static.md](static.md), [documentation.md](documentation.md) |
| Security considerations | Abuse cases 1–6 have negative tests. The security review found no vulnerability. Self-review and critic findings are fixed | [security.md](security.md), [security-review.md](security-review.md), [self-review.md](self-review.md), [critic-review.md](critic-review.md) |
