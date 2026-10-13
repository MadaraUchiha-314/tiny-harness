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

## After R5 and R6 (PR review)

`tests/unit/test_config_card.py`, 9 tests: an absent `[card]` equals the default
description; a set section reaches the built card; an unset key keeps its default; five
refusals (empty name, blank description, unknown key, duplicate skill id, empty skill
id); the example's two configurations load and pair up. Red first: collection failed on
`ImportError: cannot import name 'CardConfig'`. Then
`uv run pytest tests/unit tests/contract tests/security tests/ui`: 730 passed.
