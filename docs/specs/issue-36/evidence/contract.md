# T5 — contract snapshots

2026-10-13, branch `loop/issue-36`, Python 3.14, local Temporal dev server (`start_local`).

## `uv run pytest tests/contract`

```text
37 passed in 3.60s
exit=0
```

Snapshots changed on purpose (each regenerated with `UPDATE_API_SNAPSHOTS=1` and
reviewed in the diff):

| Snapshot | Change |
|---|---|
| `settings.schema.json` | `[agent]` (`id`, `name`, `description`); `temporal.task_queue` optional, default the agent id |
| `tiny_harness.config.txt` | `AgentConfig`, `DEFAULT_AGENT_ID`, `Settings.agent`, `TemporalConfig.task_queue: str \| None` |
| `tiny_harness.errors.txt` | `HarnessConflictError`, `HarnessAlreadyStartedError`, `HarnessStoppedError`, `HarnessNotStartedError` |
| `tiny_harness.service.txt` | `Harness`, `RouteOptions`, `harnesses_lifespan` |
| `tiny_harness.fastapi.txt` (new) | `harness_router(harness, *, tags=None) -> APIRouter` |

`agent-card.json` is **unchanged** (R7.3): the default agent at the root builds the same
card.
