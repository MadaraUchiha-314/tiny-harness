# tiny-harness

An opinionated, production-grade agent harness for customer-facing agentic workflows:
A2A 1.0 in and out, MCP tools, Agent Skills and Agent Plugins, one Temporal workflow per
task, hooks around every operation, and a TUI and a web renderer. It is being built in
the stacked pull requests of [issue #3](https://github.com/MadaraUchiha-314/tiny-harness/issues/3);
the spec chain lives under `docs/specs/issue-3/`.

## What is in the box

- An **A2A 1.0 server** (JSON-RPC and REST, streaming, push notifications) and an A2A
  client for remote agents; three extensions (task, channel, A2UI 0.9.1).
- A **core loop** of hooks around every operation: ingest, assemble, compact, call the
  model, run tools, decide completion. Intrinsic tools cover plans, sub-tasks, help
  requests, participants, skills and UI.
- **Temporal** owns the whole request lifecycle: one workflow per task, every model and
  tool call an activity, workflow-managed retries, a durable event log, continue-as-new.
- **Plugins** (Agent Plugins manifests) bring MCP servers, skills, hooks and prompt
  extensions; models are OpenAI (Responses API) and Anthropic adapters.
- **Two renderers**: a Textual TUI and a React web renderer on the official A2UI
  renderer, each an A2A client through the official SDK of its language; the web
  renderer is also hosted at
  [madarauchiha-314.github.io/tiny-harness/ui](https://madarauchiha-314.github.io/tiny-harness/ui/)
  and talks to any harness whose URL you give it.
- **Observability**: JSON logs and OpenTelemetry spans (GenAI conventions), redacted.

## Run the demo

```sh
export TEMPORAL_API_KEY="$(secret-tool lookup service temporal project tiny-harness)"
export OPENAI_API_KEY="$(secret-tool lookup service openai project tiny-harness)"
export TINY_HARNESS_PUSH_KEY="$(openssl rand -base64 32)"
bun install --cwd renderers/web && bun run --cwd renderers/web build
uv run python -m examples.demo            # A2A server + worker, web renderer at /ui
uv run tiny-harness tui --url http://127.0.0.1:8080   # as your OS user; --participant <id> to choose
```

No Temporal account? Run it with an **embedded Temporal**: the harness starts a local
Temporal dev server for its own process (loopback only, persisted beside the store) and
stops it on exit, so only the OpenAI key is needed:

```sh
unset TEMPORAL_API_KEY                    # refused in embedded mode
export OPENAI_API_KEY="$(secret-tool lookup service openai project tiny-harness)"
export TINY_HARNESS_PUSH_KEY="$(openssl rand -base64 32)"
uv run python -m examples.demo examples/demo/config.embedded.toml
uv run tiny-harness --config examples/demo/config.embedded.toml tui   # or: TUI hosting it all
```

Embedded mode is `[temporal] mode = "embedded"` in any configuration; it is for
development and single-host use, not production.

No OpenAI account either? Point the OpenAI adapter at any **OpenAI-compatible server**
with `[openai] base_url` — Ollama, OpenRouter, vLLM, LM Studio — and choose its wire API
with `api = "responses"` (the default) or `"chat_completions"`. With a local
[Ollama](https://ollama.com) and embedded Temporal, the demo runs with no key and no
network:

```sh
OLLAMA_CONTEXT_LENGTH=16384 ollama serve &   # the server first: `pull` talks to it
ollama pull qwen3:8b
unset OPENAI_API_KEY TEMPORAL_API_KEY     # a local endpoint needs no key
export TINY_HARNESS_PUSH_KEY="$(openssl rand -base64 32)"
uv run python -m examples.demo examples/demo/config.ollama.toml
```

See [getting started](https://madarauchiha-314.github.io/tiny-harness/guide/getting-started)
for what happens next and
[deployment](https://madarauchiha-314.github.io/tiny-harness/guide/deployment) for
running it for real: the server must sit behind an authenticating perimeter.

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
