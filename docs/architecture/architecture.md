# Architecture — tiny-harness

The top-level architecture index. Sub-component architectures are linked from here as
they are added (`docs/architecture/<component>.md`).

## What tiny-harness is

A tiny agent harness. The code so far is one example function, `hello_world`, in the
`tiny_harness` package; this section grows with the first work item that adds harness
behaviour.

## Repository layout and tooling

```text
tiny_harness/         the package (import as `from tiny_harness import ...`)
tests/unit/           unit tests — run by the pre-commit hook
tests/integration/    integration tests — run in CI
docs/                 VitePress site + the-loop's specs, capabilities, decisions
.github/workflows/    ci.yml (PRs), release.yml (PyPI), docs.yml (Pages)
```

The tools, and how checks flow from the pre-commit hooks into CI and releases, are in the
[tech stack guide](../guide/tech-stack). Current behaviour is in the
[repo-tooling capability](../capabilities/repo-tooling.md); the reasoning in
[decision-001](../decisions/decision-001.md).
