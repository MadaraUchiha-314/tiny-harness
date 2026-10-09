---
type: evidence
workItem: "github:MadaraUchiha-314/tiny-harness#2"
---

# Documentation: Repo tooling setup

## Capability docs

| Capability doc | What changed | History row |
|----------------|--------------|-------------|
| [repo-tooling](../../../capabilities/repo-tooling.md) | New: the Python project, hooks, CI, PyPI releases and docs site | issue-2 |
| [capabilities index](../../../capabilities/capabilities.md) | Row added for repo-tooling | n/a (index) |
| [dev-environment](../../../capabilities/dev-environment.md) | Unchanged: it covers the agent setup (instructions, Claude settings, `.the-loop/`), which this item does not change | — |

## Documentation

| Document | What changed |
|----------|--------------|
| `README.md` | Usage example, install, two-line dev setup, links to the docs site and local-development guide |
| `docs/index.md` | New: docs-site home page |
| `docs/guide/tech-stack.md` | New: tools, where each is configured, how checks flow, repository layout |
| `docs/guide/local-development.md` | New: prerequisites, `uv sync`, installing the pre-commit hooks, running each check, docs workflow |
| `docs/guide/releasing.md` | New: how versions are computed, what `release.yml` does, required GitHub/PyPI settings |
| `docs/specs/index.md` | New: landing page for the specs tree |
| `docs/architecture/architecture.md` | Repository layout and tooling section |
| `docs/decisions/decision-001.md`, `decisions.md` | New decision record and index row |
