# Local development

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — installs Python 3.14 for
  you if it is missing.
- [Node.js](https://nodejs.org/) 22 or later — the markdownlint hook runs through `npx`.
- [Bun](https://bun.sh/docs/installation) — only to work on the docs site.

## Set up

```sh
git clone https://github.com/MadaraUchiha-314/tiny-harness.git
cd tiny-harness
uv sync
```

`uv sync` creates `.venv/` in the repository root and installs the package (editable) and
every development tool, at the versions pinned in `uv.lock`. Point your editor at
`.venv/bin/python`.

## Install the git hooks

```sh
uv run pre-commit install
```

This installs two hooks:

- **pre-commit** — runs Ruff (lint and format), Pyright, the unit tests and markdownlint
  on every commit. A failure blocks the commit; Ruff's fixes are left in your working tree
  to review and stage.
- **commit-msg** — runs `cz check`, which rejects any message that is not a
  [Conventional Commit](https://www.conventionalcommits.org/) (`feat: …`, `fix: …`,
  `docs: …`, …). The message type decides the next release version, see
  [Releasing](./releasing).

Run every hook against the whole tree, as CI does:

```sh
uv run pre-commit run --all-files
```

## Run the checks one by one

| Check | Command |
|-------|---------|
| Lint | `uv run ruff check` |
| Format | `uv run ruff format` (`--check` to only report) |
| Type check | `uv run pyright` |
| Unit tests | `uv run pytest tests/unit` |
| Integration tests | `uv run pytest tests/integration` |
| All tests | `uv run pytest` |
| Commit message | `uv run cz check --rev-range origin/main..HEAD` |

## Add a dependency

```sh
uv add <package>          # runtime dependency
uv add --dev <package>    # development tool
```

Commit the updated `pyproject.toml` and `uv.lock` together; CI runs `uv sync --locked`
and fails on a lockfile that does not match.

## Work on the docs

```sh
cd docs
bun install
bun run docs:dev       # live preview at http://localhost:5173/tiny-harness/
bun run docs:build     # what CI runs; fails on dead links
```

Every page is Markdown under `docs/`. Add a page to the sidebar in
`docs/.vitepress/config.mts`; spec folders, capabilities, decisions and learnings are
listed automatically.
