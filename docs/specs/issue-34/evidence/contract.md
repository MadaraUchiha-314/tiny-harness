# T3 — contract tests

## `uv run pytest tests/contract -q`

```text
36 passed in 2.77s
```

## Deliberate snapshot changes

`docs/a2a/ext/intrinsics/spawn_subtask.json`, regenerated with `UPDATE_API_SNAPSHOTS=1`:

```diff
-        "description": "A registered remote agent id, or null for this harness",
+        "description": "An agent id listed under `agents`, or null to run this step on this harness",
```

`tests/contract/snapshots/tiny_harness.harness.core.txt`: `ContextWindowManager.assemble`
gains `agents_roster: str = '(no agents)'`, and `core_intrinsics` gains the keyword-only
`known_agents`. Both have defaults, so existing callers are unchanged. No other public
API changed. `tests/contract/test_prompts_api.py` now pins `SECTION_ORDER` literally,
with `agents` between `skills` and `rules`.
