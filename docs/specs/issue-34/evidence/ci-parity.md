# CI parity

The same commands CI runs (`.github/workflows/ci.yml`).

## `uv run pre-commit run --all-files`

```text
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
```

## `uv run pytest tests/integration`

```text
111 passed, 1011 warnings in 155.82s (0:02:35)
```

## `uv run pytest tests/contract tests/security tests/ui`

Run at task 5 (same code as now): unit, contract, security and ui together, 718 passed.
The contract and security runs above repeat it on the final code.

## `cd docs && bun run docs:build`

Run at task 6: `build complete`, no dead links.

## After R5 and R6 (PR review)

- `uv run pre-commit run --all-files`: every hook passed (ruff, ruff-format, pyright,
  unit tests, markdownlint) after one markdownlint fix (emphasis style in `tasks.md`).
- `uv run pytest tests/unit tests/contract tests/security tests/ui`: 730 passed.
- `uv run pytest tests/integration`: 112 passed.
- `cd docs && bun run docs:build`: `build complete`, no dead links (the new guide
  `sdk/example-delegation` included).
