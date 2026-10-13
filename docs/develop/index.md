# Developer guide

This section is for people who change tiny-harness itself. If you want to use
tiny-harness, read the [CLI quickstart](../cli/) or the [SDK quickstart](../sdk/).

| Page | What it covers |
|------|----------------|
| This page | Set up the repository, run the checks, work on the docs |
| [Architecture](../architecture/architecture) | How the parts fit together |
| [Tech stack](tech-stack) | The tools and where each is configured |
| [Releasing](releasing) | How a merge becomes a release |
| [Write documentation](writing-docs) | The rules for user and developer docs |
| [Capabilities](../capabilities/capabilities) | The current behaviour, one page per capability |
| [Decisions](../decisions/decisions) and [specs](../specs/) | Why things are the way they are |

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

## End-to-end tests

The end-to-end tests run the [support agent example](../sdk/example) against a real
model:

```sh
uv run pytest tests/e2e -q -m e2e                      # the example, then the crash tests
uv run pytest tests/e2e -q -m e2e -k crash_recovery    # only the kill -9 tests
```

- `tests/e2e/test_demo.py` drives the conversation through the A2A client and checks
  the states, the orders server's ledger and the trace.
- `tests/e2e/test_demo_ollama.py` runs the same flow on a local Ollama, with no key.
- `tests/e2e/test_crash_recovery.py` kills the worker with `SIGKILL` during a tool call
  and while the task waits, starts it again, and proves from Temporal's history that no
  model call ran twice.

Each run uses its own task queue, port and folder under
`~/.cache/tiny-harness-logs/e2e/`. Set `TINY_HARNESS_E2E_EVIDENCE=<dir>` to also copy
the transcript, the final task, the trace and the history there. Without the secrets,
the tests skip and name the missing variable.

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
`docs/.vitepress/config.mts`. Spec folders, capabilities, decisions and learnings are
listed automatically. Follow [Write documentation](writing-docs).

## Coding agents

The repository configures two plugins for Claude Code in `.claude/settings.json`:

- **the-loop**: the process that every change follows. See `AGENTS.md`.
- **archify**: draws interactive architecture diagrams from the code. It comes from
  the local marketplace in `.claude/marketplace/`, pinned to a reviewed release.

Trust the repository's settings when Claude Code asks, and both plugins install.

The project skill `docs-writing` lives in `.agents/skills/`, where Codex finds it.
`.claude/skills/docs-writing` links to the same folder for Claude Code. To use archify
with Codex, install it with `npx skills add tt-a1i/archify --skill archify --agent codex`.
