# T15, T16 — docs build and static checks

2026-10-13, branch `loop/issue-36`.

## T15: `cd docs && bun run docs:build`

```text
build complete in 21.13s.
exit=0
```

The build fails on a dead link, so the new pages' links (`sdk/mount.md`,
`configuration/agent.md`, the deploy and server pages) resolve.

## T16: `uv run pre-commit run --all-files`

```text
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
exit=0
```

The first run failed markdownlint MD012 (a double blank line at the end of
`evidence/integration.md`). The fix is in the same commit, and this is the rerun.
