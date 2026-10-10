# Getting started

The quickest way to see tiny-harness work is the demo under `examples/demo`: one harness
instance on Temporal Cloud, the `gpt-6.1-sol` model, two MCP servers, a skill, and both
renderers on one task: *"Refund order #48213: the customer says the blender arrived
cracked. Check the order and propose a resolution."*

## What you need

- The [local development](local-development) setup (`uv sync`), plus Bun for the web
  renderer.
- A Temporal Cloud namespace reachable with an API key, and an OpenAI key. The demo reads
  both from the environment only; nothing is read from a file. The project keeps them in
  the GNOME keyring:

```sh
export TEMPORAL_API_KEY="$(secret-tool lookup service temporal project tiny-harness)"
export OPENAI_API_KEY="$(secret-tool lookup service openai project tiny-harness)"
export TINY_HARNESS_PUSH_KEY="$(openssl rand -base64 32)"   # encrypts push-config tokens at rest
```

A missing variable stops the process at startup with the variable's name; there is no
anonymous or local fallback.

### No Temporal account: embedded mode

Every configuration can run with an **embedded Temporal** instead:
`[temporal] mode = "embedded"`, no `address`, and no `TEMPORAL_API_KEY` (it is refused in
that mode, so an embedded run is never confused with a Cloud one). The harness starts the
Temporal CLI dev server through the Temporal SDK, bound to `127.0.0.1` and persisted to
`temporal.sqlite3` beside the store, and stops it when the process exits. The first run
downloads the CLI once into `~/.cache/tiny-harness/temporal` (or set
`temporal.embedded.binary_path` to an installed `temporal`).

```sh
unset TEMPORAL_API_KEY
uv run python -m examples.demo examples/demo/config.embedded.toml   # server + worker + Temporal
uv run tiny-harness --config examples/demo/config.embedded.toml tui # or the TUI hosting all three
```

`tiny-harness tui` with no `--url` in embedded mode starts the harness in its own process
and writes the harness's logs to `tiny-harness.log` beside the store, so they never draw
over the TUI. The same configuration drives the programmatic entry point,
`tiny_harness.service.running_harness(settings)`. Embedded mode is for development and
single-host use; see [deployment](deployment#embedded-temporal-is-not-a-production-deployment).

### No OpenAI account: any OpenAI-compatible server

The OpenAI adapter talks to any server that implements OpenAI's API. Set
`[openai] base_url` to the server (`http://127.0.0.1:11434/v1` for a local Ollama,
`https://openrouter.ai/api/v1` for OpenRouter), `model` to a name that server knows, and
`api` to `"chat_completions"` when the server implements only Chat Completions (the
default, `"responses"`, is OpenAI's Responses API). `OPENAI_API_KEY` becomes optional
with a `base_url` — a local Ollama needs none — and when it is set it is sent to that
server. Set `context_window_tokens` to the window the server actually gives the model,
so compaction triggers in time.

`examples/demo/config.ollama.toml` combines this with embedded Temporal, so the whole
demo runs **offline**:

```sh
ollama pull qwen3:8b                          # once, with a network; any tool-calling model
OLLAMA_CONTEXT_LENGTH=16384 ollama serve &    # MUST match context_window_tokens
unset OPENAI_API_KEY TEMPORAL_API_KEY
uv run python -m examples.demo examples/demo/config.ollama.toml
```

A fully offline run also needs what the first embedded run downloads — the Temporal CLI
(or `temporal.embedded.binary_path`) — and the demo's MCP servers' environment
(`uv sync`) already on disk. The startup log names where model calls go:
`model endpoint http://127.0.0.1:11434 api=chat_completions model=qwen3:8b`.

## Run the demo

```sh
bun install --cwd renderers/web && bun run --cwd renderers/web build   # the web renderer
uv run python -m examples.demo                                         # server + worker
```

The process prints the two surfaces:

- **Web renderer** at `http://127.0.0.1:8080/ui/`: type the complaint in the composer and
  watch the stream.
- **TUI** in another terminal: `uv run tiny-harness tui --url http://127.0.0.1:8080`. It
  sends as your OS user name; `--participant <id>` asserts another id. The id is
  self-asserted, like the web renderer's `?participant=`.

Both are A2A clients of the same server through the official SDKs (`a2a-sdk` for the
TUI, `@a2a-js/sdk` for the web), so a task started in one shows up in the other. The web
renderer is also hosted on this site at [`/ui/`](https://madarauchiha-314.github.io/tiny-harness/ui/):
enter a harness URL in its header (or open it with `?server=<url>`) and it talks to that
harness directly, provided the harness allows the site's origin in `cors_origins`.

## What happens

```mermaid
sequenceDiagram
    participant R as Renderer (web or TUI)
    participant S as A2A server
    participant W as Worker (Temporal workflow)
    participant M as MCP servers (orders, policy)
    participant L as gpt-6.1-sol
    R->>S: SendStreamingMessage (complaint)
    S->>W: update-with-start TaskWorkflow
    W->>L: turn 1 (system prompt, skill, tools)
    L-->>W: load_skill, create_plan, get_order, policy.lookup
    W->>M: tools/call get_order, lookup
    W->>L: turn n
    L-->>W: emit_ui (A2UI card), ask_participant
    W-->>S: artifact a2ui, status INPUT_REQUIRED
    S-->>R: the card and the question
    R->>S: SendStreamingMessage (A2UI action or text reply)
    S->>W: inbox update
    W->>M: ship_replacement (not idempotent, never retried)
    W-->>S: status COMPLETED with the summary
```

1. The task is **SUBMITTED** then **WORKING**; the agent loads the `support-agent` skill,
   creates a plan and calls the `orders` and `policy` MCP tools.
2. An **A2UI card** arrives as an artifact: the resolution options and a *Confirm* button
   rendered by the official A2UI renderer in the web renderer and mapped to Textual widgets
   in the TUI.
3. The agent asks the reporter (`ask_participant`) and the task waits in
   **INPUT_REQUIRED**. Press the button or answer in text.
4. The agent ships the replacement or issues the refund and the task reaches
   **COMPLETED** with a two-sentence summary.

Every span of the run is appended to `examples/demo/.state/trace.jsonl` (one JSON object
per line, secrets redacted) and the SQLite store sits beside it. Delete `.state/` to start
over.

## Run the same flow as a test

```sh
uv run pytest tests/e2e -q -m e2e                      # the demo, then the two crash scenarios
uv run pytest tests/e2e -q -m e2e -k crash_recovery    # only the kill -9 scenarios
```

`tests/e2e/test_demo.py` drives the conversation through the A2A client (it presses the
card's button for the first question) and asserts the states, the ledger of the orders
server and the trace. `tests/e2e/test_crash_recovery.py` runs the server and the worker
as separate processes, kills the worker with `SIGKILL` during an idempotent tool call and
again while the task waits for input, restarts it, and reads Temporal's history to prove
no LLM call ran twice. Each run gets its own task queue, port and state directory under
`~/.cache/tiny-harness-logs/e2e/`. Set `TINY_HARNESS_E2E_EVIDENCE=<dir>` to also copy the
redacted transcript, final task, trace and history summaries there. Without the secrets,
the tests skip with the missing variable's name.

## Next

- [Deployment](deployment): running the server and workers for real, the perimeter they
  need, and what is retained where.
- [Capabilities](../capabilities/capabilities): the current behaviour, one page per
  requirement group.
- [The A2A extensions](../a2a/extensions): what the task and channel data parts carry.
