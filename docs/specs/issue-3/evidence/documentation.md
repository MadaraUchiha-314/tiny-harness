# Documentation evidence — issue-3

What the capability-docs gate checks, and where it is met.

## Capability docs

One doc per requirement group under `docs/capabilities/`, each from the-loop's
capability template (what it is, normative current behaviour, design pointers, history
rows to this spec and to decisions 002–004):

| Requirement group | Capability doc |
|---|---|
| R1 | [entities-and-registry](../../../capabilities/entities-and-registry.md) |
| R2 | [hooks](../../../capabilities/hooks.md) |
| R3 | [plugins](../../../capabilities/plugins.md) |
| R4, R5 | [prompts-and-skills](../../../capabilities/prompts-and-skills.md) |
| R6 | [tools](../../../capabilities/tools.md) |
| R7 | [remote-agents](../../../capabilities/remote-agents.md) |
| R8, R9 | [tasks-and-plans](../../../capabilities/tasks-and-plans.md) |
| R10 | [context-window](../../../capabilities/context-window.md) |
| R11 | [persistence](../../../capabilities/persistence.md) |
| R12, R13 | [participants-and-channels](../../../capabilities/participants-and-channels.md) |
| R14, R15 | [a2a-server](../../../capabilities/a2a-server.md) |
| R16 | [heartbeat](../../../capabilities/heartbeat.md) |
| R17 | [observability](../../../capabilities/observability.md) |
| R18 | [models](../../../capabilities/models.md) |
| R19 | [durable-execution](../../../capabilities/durable-execution.md) |
| R20 | [surfaces-and-renderers](../../../capabilities/surfaces-and-renderers.md) |
| R21 | [configuration](../../../capabilities/configuration.md) |
| R22, R23 | [repo-tooling](../../../capabilities/repo-tooling.md) (history row for issue-3: module tree, `Any` ban, contract tests) |
| R24 | [demo](../../../capabilities/demo.md) |

`docs/capabilities/capabilities.md` indexes them by column (harness, service, surfaces,
repository). `docs/architecture/architecture.md` was rewritten from the one-function
placeholder to the layer map, the module table and a request's life.

## Guides and reference pages

- `docs/guide/getting-started.md`: the demo end to end, what happens, the e2e tests.
- `docs/guide/deployment.md`: the perimeter requirement (decision-003), processes,
  the configuration and secrets tables with the keyring lookups, retention per data kind
  (store TTLs, Temporal Cloud history retention, trace backend), observability.
- `docs/a2a/extensions.md`, `docs/a2a/ext/task/v1.md`, `docs/a2a/ext/channel/v1.md`: the
  three advertised extensions; the task and channel pages embed the committed schemas so
  the extension URIs resolve to documentation on the published site.
- `README.md`: what is in the box and how to run the demo.

## Checks

| Check | Command | Outcome |
|---|---|---|
| markdownlint | `npx markdownlint-cli2 "docs/**/*.md" README.md` (the pre-commit hook) | 0 issues |
| docs build | `bun run --cwd docs docs:build` | build complete, no dead links |
| nav | `docs/.vitepress/config.mts`: Guide gains Getting started and Deployment; a new A2A group; capabilities are listed from the directory | — |

Decisions 002–004 are linked from the capability docs that depend on them
(durable-execution, a2a-server, participants-and-channels, hooks, tools, tasks-and-plans).
