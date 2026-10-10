# Capabilities — tiny-harness

The organized view of the specs: one living doc per capability, each the single source
of truth for that capability's current behaviour, with history rows tracing every
behaviour back to the specs (`docs/specs/<id>/`) and decisions that produced it.
Affected docs are updated in the same PR as the work item that changes behaviour.

## The harness

| Capability | What it covers |
|------------|----------------|
| [entities-and-registry](entities-and-registry.md) | One interface per entity kind, `(kind, id, version)` references, one registry with local and remote entries. |
| [hooks](hooks.md) | `pre`/`in`/`post` on every operation, the executor chain, remote executors, the providers. |
| [plugins](plugins.md) | Agent Plugins 1.0.0 from a directory or code, the namespace directory, containment rules, the built-in plugin. |
| [prompts-and-skills](prompts-and-skills.md) | The markdown system prompt and its sections; Agent Skills with progressive disclosure through tools. |
| [tools](tools.md) | MCP tool sources, the validating invoker, intrinsic tools, provider-safe names. |
| [remote-agents](remote-agents.md) | Delegation to A2A 1.0 agents: card validation, sub-tasks tracked by remote status. |
| [tasks-and-plans](tasks-and-plans.md) | The A2A task with the task extension, plans as DAGs, sub-tasks, the core loop. |
| [context-window](context-window.md) | Typed agent state, templated context ordered for caching, compaction policies. |
| [persistence](persistence.md) | The store entity, the SQLite default, what is persisted where, retention. |
| [participants-and-channels](participants-and-channels.md) | Roles, channels over A2A, help requests and `INPUT_REQUIRED`, membership. |
| [models](models.md) | The LLM entity over OpenAI and Anthropic, the System One interface. |

## The service

| Capability | What it covers |
|------------|----------------|
| [a2a-server](a2a-server.md) | Every A2A 1.0 verb, the card, streaming from the event log, the inbox, push, limits, access policy. |
| [durable-execution](durable-execution.md) | One Temporal workflow per task, activities, workflow-managed retries, continue-as-new, the sandbox. |
| [heartbeat](heartbeat.md) | The schedule that polls channels, snapshots tasks and sweeps retention. |
| [observability](observability.md) | JSON logs and GenAI spans from the hooks, redaction, OTLP/Langfuse/file export. |
| [configuration](configuration.md) | `Settings`, secrets from the environment, the CLI and runtime. |

## The surfaces

| Capability | What it covers |
|------------|----------------|
| [surfaces-and-renderers](surfaces-and-renderers.md) | Surface and renderer entities, A2UI 0.9.1, the Textual TUI, the React web renderer. |
| [demo](demo.md) | The runnable definition of done and its e2e and crash-recovery tests. |

## The repository

| Capability | What it covers |
|------------|----------------|
| [dev-environment](dev-environment.md) | How an agent session is set up in this repo: `CLAUDE.md`/`AGENTS.md`, `.claude/settings.json` and the-loop's config under `.the-loop/`. |
| [repo-tooling](repo-tooling.md) | The Python project, pre-commit hooks, CI, PyPI releases and the docs site. |
