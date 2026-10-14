---
type: evidence
workItem: issue-36
---

# Documentation: mount tiny-harness agents onto an existing FastAPI or Starlette app

## Capability docs

| Capability doc | What changed | History row |
|----------------|--------------|-------------|
| `docs/capabilities/a2a-server.md` | `Harness` and `asgi_app()`, the 503 gate, the exact mount check, routes built before start, the FastAPI router, `public_url`, `RouteOptions`, the participant resolver with strict mode, task and push ownership by queue | issue-36 |
| `docs/capabilities/durable-execution.md` | `TemporalPool`, one queue per agent, `Claims`, the agent id on activities | issue-36 |
| `docs/capabilities/heartbeat.md` | One schedule per agent; the scan filtered to the agent's queue | issue-36 |
| `docs/capabilities/configuration.md` | `[agent] id`; the queue defaults to it; the new exports and the `fastapi` extra; `self` at `public_url`; local peer cards | issue-36 |
| `docs/capabilities/observability.md` | The agent id on log lines and spans; the process secret registry | issue-36 |
| `docs/capabilities/remote-agents.md` | Same-process peers get a card built from their settings | issue-36 |
| `docs/architecture/architecture.md` | Section "Agents in a host app" with a diagram | (index, no history table) |
| `docs/decisions/decision-009.md` | New decision: isolation by queue, refused shared stores, local peer cards, strict participant mode | — |

## Documentation

| Document | What changed |
|----------|--------------|
| `docs/sdk/mount.md` (new) | SDK guide: Starlette quickstart, FastAPI, several agents, peers, your own login, options, errors |
| `docs/configuration/agent.md` (new) | The `[agent] id` setting |
| `docs/configuration/temporal.md` | `task_queue` defaults to the agent id; a shared `database_path` shares one embedded Temporal |
| `docs/configuration/server.md` | A path in `base_url` is the mount path |
| `docs/configuration/index.md`, `docs/sdk/index.md`, `README.md`, `docs/.vitepress/config.mts` | Links to the new pages |
| `docs/sdk/deploy.md` | Who checks the user when agents are mounted; one agent id per namespace across processes |
| `examples/multi_agent/README.md` (new) | Run the five-agent example with Starlette or FastAPI |
