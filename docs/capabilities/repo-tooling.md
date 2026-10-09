# Capability: repo-tooling

> The Python project, its checks, its git hooks, CI, releases to PyPI and the docs site.

## What it is

The toolchain every change to tiny-harness passes through. The pre-commit hooks define the
checks; CI and the release workflow run the same hooks. The how-to lives in the
[guide](../guide/local-development); this page states the behaviour.

## Current behaviour

- The project SHALL be the `tiny_harness` distribution, built by `uv_build` from the
  top-level `tiny_harness/` package, requiring Python 3.14 or later.
- `uv sync` SHALL create `.venv/` in the repository root from `uv.lock`; CI SHALL fail on
  a stale lockfile (`uv sync --locked`).
- The package SHALL expose `hello_world()`, returning `"Hello, world!"`.
- The `pre-commit` hook SHALL run ruff (lint, format), pyright (strict), the unit tests
  and markdownlint; the `commit-msg` hook SHALL reject non-Conventional Commit messages.
  `uv run pre-commit install` installs both.
- On every pull request, `ci.yml` SHALL run the pre-commit hooks over all files, the
  integration tests and the docs build, with a read-only token.
- On every push to `main`, `release.yml` SHALL run `ci.yml`, then — when the commits
  since the last tag warrant it — bump the version with commitizen, push the `bump:`
  commit and `v<version>` tag, and publish to PyPI via Trusted Publishing from the
  `pypi` environment. Nothing releasable means no publish.
- On every push to `main` that touches `docs/`, `docs.yml` SHALL build the VitePress site
  and deploy it to GitHub Pages at `/tiny-harness/`.

## Design

[issue-2 design](../specs/issue-2/design.md), [decision-001](../decisions/decision-001.md).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-2 | Initial toolchain: uv, ruff, pyright, pytest, commitizen, pre-commit, CI, PyPI release, VitePress docs | [spec](../specs/issue-2/), [issue #2](https://github.com/MadaraUchiha-314/tiny-harness/issues/2), [PR #5](https://github.com/MadaraUchiha-314/tiny-harness/pull/5), [decision-001](../decisions/decision-001.md) |
