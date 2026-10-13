# T1 — unit tests

Commit `1e92d8b` (the implementation; later commits change docs only).

## `uv run pytest tests/unit -q`

```text
571 passed in 8.11s
```

New tests for issue-34: `tests/unit/agents/test_roster.py` (roster builder),
`tests/unit/core/test_context.py` (`agents` section), `tests/unit/core/test_spawn_agents.py`
(unknown, empty, known and null `agent`; registry read at call time) and
`tests/unit/prompts/test_prompt.py` (`## agents` content, `extends: agents`).
