# Type and lint gates — T13

`uv run pre-commit run --all-files` on 2026-10-10 at the head of the Layer 9 stack. The
hooks are the same definition CI runs (decision-001). The `Any` gate is ruff's `ANN401`
plus a banned import of `typing.Any` under `tiny_harness/`; the grep below shows the only
two matches of the word are prose in docstrings.

```text
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
## Any grep gate
tiny_harness/jsontypes.py:1:"""Typed JSON aliases, so no ``dict[str, Any]`` appears anywhere (R22.2)."""
tiny_harness/harness/hooks/remote.py:9:Any transport failure, non-conforming reply or server-side error raises
matches: 2
```

`uv run pyright` on the whole repository: `0 errors, 0 warnings, 0 informations`.
`bun run --cwd renderers/web build` (which runs `tsc --noEmit` under `strict`): clean.
`bun run --cwd docs docs:build`: build complete.
