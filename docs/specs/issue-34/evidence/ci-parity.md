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
