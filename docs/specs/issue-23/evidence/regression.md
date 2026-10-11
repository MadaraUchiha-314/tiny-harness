---
type: evidence
workItem: issue-23
row: T12
---

# Full repository checks (T12)

Every pre-commit hook passes over all files at `34dccbc` — the same command CI's
`checks` job runs. The docs site also builds (CI's `docs` job).

```text
$ uv run pre-commit run --all-files
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
```

```text
$ (cd docs && bun install --frozen-lockfile && bun run docs:build)
build complete in 17.43s.
```
