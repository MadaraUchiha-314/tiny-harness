# Decision 001: Python toolchain and one definition of the checks

- **Status:** proposed (accepted when PR #5 is approved)
- **Date:** 2026-10-08
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #2](https://github.com/MadaraUchiha-314/tiny-harness/issues/2)

## Context

tiny-harness had no code or tooling. Issue #2 named most tools (uv, ruff, pyright,
pytest, commitizen, pre-commit, VitePress, GitHub Actions, PyPI); this record covers the
choices it left open and how the pieces connect.

## Decision

1. **Python 3.14**, the latest stable release on 2026-10-08 (3.15 was at rc2).
2. **`uv_build`** as the build backend, with a flat layout (`tiny_harness/` at the root).
3. **The pre-commit hooks are the only definition of lint, type-check and unit-test.**
   `ci.yml` runs them with `pre-commit run --all-files`, plus integration tests and the
   docs build. `release.yml` calls `ci.yml` (`workflow_call`) before it bumps and
   publishes. All Python tools run through `uv run`, pinned by `uv.lock`.
4. **commitizen computes the version** with `version_provider = "uv"`, so `pyproject.toml`
   and `uv.lock` change in the same `bump:` commit. `major_version_zero = true`; the
   first release is `0.1.0`.
5. **Pyright in strict mode** from the first line of code.
6. **markdownlint** in the hooks (the-loop's lint-all-files rule), pinned via `npx`.
7. **Bun** runs the VitePress docs, the same stack as the-loop's site.

## Consequences

- Adding a check means editing `.pre-commit-config.yaml` once; local and CI cannot drift.
- Every release re-runs CI on `main` (about two minutes) even though the PR passed it.
- Contributors need Node for the markdownlint hook, and Bun only to work on the docs.
- Strict typing makes untyped third-party libraries cost a stub or a `cast`.

## Alternatives considered

- **hatchling or setuptools as the backend** — an extra tool for no benefit at this size.
- **Duplicating the check steps in each workflow** — two definitions drift.
- **`pep621` version provider** — leaves `uv.lock` one version behind after every bump.
- **npm for the docs** — works, but differs from the reference site the issue points to.
