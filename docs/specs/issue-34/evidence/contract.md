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

## After R5 (PR review): `[card]`

`tests/contract/snapshots/settings.schema.json` and `tiny_harness.config.txt`,
regenerated on purpose with `UPDATE_API_SNAPSHOTS=1`. They gain `CardConfig`,
`CardSkillConfig` and `Settings.card`:

```diff
+model CardConfig(name: str | None = ..., description: str | None = ..., version: str | None = ..., skills: tuple[tiny_harness.config.CardSkillConfig, ...] = ...)
+model CardSkillConfig(id: <class 'str'>, name: <class 'str'>, description: <class 'str'> = ..., tags: tuple[str, ...] = ..., examples: tuple[str, ...] = ...)
-model Settings(…, agents: tuple[tiny_harness.config.RemoteAgentSpec, ...] = ..., store: …)
+model Settings(…, agents: tuple[tiny_harness.config.RemoteAgentSpec, ...] = ..., card: <class 'tiny_harness.config.CardConfig'> = ..., store: …)
```

`tests/contract/snapshots/agent-card.json` did **not** change: with no `[card]`, the
card is the same as before (R5.3). `uv run pytest tests/contract`: 36 passed.
