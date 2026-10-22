# T13 — static checks

Work item issue-38, activity T13. ruff, pyright strict, markdownlint, pytest unit (the
pre-commit hooks), and the web type-check. CI runs pre-commit after `uv sync --locked`
(no extras), so the checks ran both with all extras and without them.

2026-10-22, branch `issue-38-multimodal` at `22701e9`.

## `uv run pre-commit run --all-files` (all extras)

```text
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
exit=0
```

## `cd renderers/web && bun run typecheck`

```text
$ bun run generate && tsc --noEmit
$ bun run scripts/generate-types.ts
generated 4 type file(s) into src/generated/
exit=0
```

## CI parity: no extras

```text
$ uv sync --locked
Uninstalled 3 packages in 6ms
 - pillow==13.0.0
 - sounddevice==0.5.6
 - textual-image==0.14.2
$ uv run pyright
0 errors, 0 warnings, 0 informations
$ uv run pre-commit run --all-files
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
exit=0
$ uv sync --locked --all-extras
Installed 3 packages in 8ms
 + pillow==13.0.0
 + sounddevice==0.5.6
 + textual-image==0.14.2
```

pyright strict passes without `sounddevice`, `textual-image` and `pillow` installed: the
optional imports in the TUI are typed for their absence.

markdownlint in pre-commit checks tracked files. The verification evidence was linted by
the same hook when it was committed.
