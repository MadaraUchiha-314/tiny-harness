# Unit tests — T1

Run on branch `loop/issue-3-l9-demo` at the head of the Layer 9 stack (2026-10-10, after both self-review rounds and the critic round), the
same command the pre-commit hook runs. Every entity, loader, adapter, the registry, the
hook manager, the plan validator, the context window manager, compaction, the redactor
and the configuration have unit tests behind public interfaces (R23.3).

```text
## uv run pytest tests/unit -q
........................................................................ [ 36%]
........................................................................ [ 72%]
........................................................                 [100%]
200 passed in 4.31s
```

## By layer (stacked pull request)

| Layer | PR | Test modules | Tests |
|---|---|---|---|
| 1 — entities, hooks, configuration, errors | #7 | `tests/unit/entities`, `tests/unit/hooks`, `test_config.py`, `test_errors.py`, `test_layout.py` | 83 |
| 2 — plugins, prompts, skills | #8 | `tests/unit/plugins`, `tests/unit/prompts`, `tests/unit/skills` | 21 |
| 3 — models, tools | #9 | `tests/unit/models` (incl. `test_wire_names.py`), `tests/unit/tools` | 22 |
| 4 — core loop, state, persistence, channels | #10 | `tests/unit/core`, `tests/unit/persistence`, `tests/unit/channels` | 34 |
| 5 — service: durable, A2A, CLI | #11 | `tests/unit/service` (incl. `test_app_routes.py`, `test_bridge.py`, `test_inbox_envelopes.py`), `test_workflows.py` | 33 |
| 6 — observability | #12 | `tests/unit/service/test_o11y.py` | counted in layer 5 |
| 7 — A2UI, TUI | #13 | `tests/unit/a2ui`, `tests/ui` (T5/T9) | 7 (+ 9 UI) |
| 8 — web renderer | #14 | `renderers/web/src/App.test.tsx` (vitest) | 3 |
| 9 — demo | this PR | `tests/e2e` (T4/T12, see `e2e.md`) | 3 |

Web renderer unit tests (`bun run --cwd renderers/web test`):

```text
 Test Files  1 passed (1)
      Tests  3 passed (3)
```
