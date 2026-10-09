---
type: evidence
workItem: "github:MadaraUchiha-314/tiny-harness#2"
---

# Verification: Repo tooling setup

`test-planning` was declared away, so the proof lives here. Raw output:
[output.md](output.md). Screenshots: [home](docs-home.png),
[local development guide](docs-local-development.png), [a spec page](docs-specs.png).

## Verification results

| What was verified | Command | Outcome | Evidence |
|-------------------|---------|---------|----------|
| Fresh clone syncs from the lock into `.venv/` on Python 3.14 (R1.2–R1.4) | `uv sync --locked`; `.venv/bin/python --version` | pass — 3.14.7 | [output.md § Fresh clone](output.md#fresh-clone-setup-hooks-tests-build-docs) |
| Both git hooks install with one command (R5.2) | `uv run pre-commit install` | pass — pre-commit + commit-msg | same |
| All hooks pass on the delivered tree (R3.2, R5.1) | `uv run pre-commit run --all-files` | pass — 5/5 | same |
| Unit, workflow-invariant and integration tests pass (R2.2–R2.4, R6, R7, abuse cases 1–3) | `uv run pytest -v` | pass — 16 passed | same |
| `from tiny_harness import hello_world` works (R1.5, R2.1) | `uv run python -c "…"` | pass — `Hello, world!` | same |
| Distribution builds as `tiny_harness` (R1.1) | `uv build` | pass — sdist + wheel | same |
| Docs site builds, dead-link check included (R8.1–R8.2) | `bun install --frozen-lockfile && bun run docs:build` | pass | same; screenshots |
| Non-conventional commit message rejected; conventional accepted (R4.2, R4.3) | `git commit -am "bad message"` / `"docs: good message"` | pass — exit 1 / exit 0 | [output.md § Negative checks](output.md#negative-checks-the-git-hooks-block-bad-commits) |
| Lint error, failing unit test and type error each block the commit (R5.3) | commits with an unused import, a broken greeting, an untyped function | pass — exit 1 each | same |
| Release computes 0.0.0 → 0.1.0 and bumps `pyproject.toml` + `uv.lock` together (R7.3) | `uv run cz bump --dry-run --yes`, then `cz bump --yes` in a throwaway clone | pass | [output.md § Release](output.md#release-version-computation-dry-run) |
| PR CI runs hooks, integration tests and docs build, all green (R6.1–R6.4) | `the-loop pr status …#5` | pass — 3/3 success | [output.md § Pull request CI](output.md#pull-request-ci) |
| Mermaid diagrams render on the site (PR #5 review) | `bun run docs:build`; headless screenshot of `/guide/releasing` | pass | [docs-mermaid.png](docs-mermaid.png) |
| Live release to PyPI and Pages deploy (R7.2–R7.6 live, R8.3) | — | **not run** — these workflows run only on `main`, after merge | Proved before merge by the workflow tests and the dry run; to be observed on the first merge |
