# tiny-harness

An opinionated, production-grade agent harness for customer-facing agentic workflows:
A2A 1.0 in and out, MCP tools, Agent Skills and Agent Plugins, one Temporal workflow per
task, hooks around every operation, and a TUI and a web renderer. It is being built in
the stacked pull requests of [issue #3](https://github.com/MadaraUchiha-314/tiny-harness/issues/3);
the spec chain lives under `docs/specs/issue-3/`.

## Install

```sh
pip install tiny_harness
```

## Develop

```sh
uv sync                    # creates .venv/ with every dev tool
uv run pre-commit install  # lint, type-check, unit tests + commit-message hooks
```

See [local development](https://madarauchiha-314.github.io/tiny-harness/guide/local-development)
for the full guide, and the [documentation site](https://madarauchiha-314.github.io/tiny-harness/)
for the tech stack, architecture and decisions.
