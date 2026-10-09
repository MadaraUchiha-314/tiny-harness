---
type: evidence
workItem: "github:MadaraUchiha-314/tiny-harness#2"
---

# Final validation: Repo tooling setup

Summarised from [verification.md](verification.md); raw output in [output.md](output.md).

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| R1.1–R1.5 — `tiny_harness` project, Python 3.14, uv + `.venv/`, `uv.lock` enforced, `from tiny_harness import …` | Fresh clone: `uv sync --locked` → `.venv/` on 3.14.7; `uv build` → `tiny_harness-0.0.0` sdist + wheel; CI's `uv sync --locked` | verification rows 1, 5, 6 |
| R2.1–R2.4 — `hello_world`, unit test, Gherkin-documented integration test | `uv run pytest -v` → 16 passed, including the wheel-install scenario | row 4 |
| R3.1–R3.3 — ruff, pyright strict, pytest configured and clean | `uv run pre-commit run --all-files` → 5/5 passed | row 3 |
| R4.1–R4.3 — commitizen rejects bad messages, accepts conventional ones | `git commit -am "bad message"` exit 1; `"docs: good message"` exit 0 | row 8 |
| R5.1–R5.4 — hooks installed by one command; lint, type and test failures block | `uv run pre-commit install`; three blocked commits | rows 2, 9 |
| R6.1–R6.4 — PR CI runs hooks, integration tests, docs build | PR #5 checks: 3/3 success | row 11 |
| R7.1–R7.6 — release on merge via Trusted Publishing | Workflow-invariant tests (jobs chained, scopes, env `pypi`, bump-skip guard); `cz bump` computes 0.0.0 → 0.1.0 and bumps `pyproject.toml` + `uv.lock` together. **The live run happens only after merge** | rows 4, 10, 12 |
| R8.1–R8.5 — VitePress site, Pages deploy, tech-stack and local-dev docs, README links | `bun run docs:build` passes; screenshots of rendered pages; `docs.yml` tested. **Pages deploy runs only after merge** | row 7, [home](docs-home.png), [guide](docs-local-development.png), [spec page](docs-specs.png) |
| Security abuse cases 1–4 | Workflow-invariant tests; `/security-review` with no findings | [security-review.md](security-review.md) |
