---
type: evidence
workItem: issue-19
row: T10
---

# Regression (T10)

CI's exact commands pass at `420df50`: the pre-commit hooks over every file, and the
integration, contract, security and UI suites (117 passed, 4 UI snapshots unchanged).
Existing configurations load unchanged: `tests/unit/test_config.py` and
`tests/unit/models/test_openai.py`, the pre-existing Responses request-mapping test, pass
unedited.

## Pre-commit, all files

```text
$ uv run pre-commit run --all-files
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
```

(`Conventional Commits (commitizen)` is a `commit-msg` hook; it passed on every commit of
the branch.)

## CI's test command

```text
$ env -u OPENAI_API_KEY -u TEMPORAL_API_KEY uv run pytest -q tests/integration tests/contract tests/security tests/ui
--------------------------- snapshot report summary ----------------------------
4 snapshots passed.
117 passed, 360 warnings in 96.10s (0:01:36)
```

The warnings are Temporal's and Pydantic's existing deprecation notices.

## Environment note

The first attempt at this command failed inside `pytest-textual-snapshot`
(`EOFError: Ran out of input`) because the machine's `/tmp` hit its per-user quota —
other sessions' files, not this change. Re-run with `TMPDIR` on the home filesystem, it
passed as above.
