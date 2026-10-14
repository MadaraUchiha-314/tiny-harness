# T14 — manual walkthrough of `examples/multi_agent`

2026-10-13, branch `loop/issue-36`. The FastAPI variant ran with a real OpenAI model
(`gpt-6.1-sol`, key from `OPENAI_API_KEY`, never written down) and embedded Temporal.

## Steps and outcomes

| # | Step (per `examples/multi_agent/README.md`) | Outcome |
|---|---|---|
| 1 | `export OPENAI_API_KEY=…` then `uv run python -m examples.multi_agent.app_fastapi` | **Failed at first**: `ConfigError … must not be set when temporal.mode is embedded variable=TEMPORAL_API_KEY`. This machine exports `TEMPORAL_API_KEY` for other work. The error is clear, but the README did not say it. **Fixed**: the README now says `unset TEMPORAL_API_KEY` in step 1 |
| 2 | The same, with `TEMPORAL_API_KEY` unset | Started in about 7 s. The log shows `agent a started at http://127.0.0.1:8090/agents/a` … `agent e started …`, one embedded dev server |
| 3 | `curl` each card | `a Front desk http://127.0.0.1:8090/agents/a/`, `b Billing …/agents/b/`, `c Shipping …/agents/c/`, `d Ledger …/agents/d/`, `e Reports …/agents/e/` |
| 4 | Open `/docs` | Five groups `A2A: a` … `A2A: e`, 16 operations each. Screenshot: [`manual/openapi-docs.png`](manual/openapi-docs.png) |
| 5 | Ask agent a: "I was charged twice for invoice 7. Please ask billing to check." | a answered and parked (`INPUT_REQUIRED`) asking which participant handles billing. **It did not delegate**: the system prompt does not list the registered remote agents, so the model does not know that `b` is billing. That is issue-34's work (branch `feat/issue-34-agents-visible`), not this item's |
| 6 | Ask agent a, naming the agent: "… Delegate this with spawn_subtask to the agent with id b (the billing agent) …" | a delegated. The server log shows a fetch `GET /agents/b/.well-known/agent-card.json` on first use and JSON-RPC calls to `POST /agents/b/` through the same app. a's task shows sub-task `<id>.1` on agent `b` in state `INPUT_REQUIRED` (b asked a question back). a's reply: "I've delegated the duplicate charge for invoice 7 to billing agent **b** …" |
| 7 | Log lines | 50 lines carry `"agent": "a"` and 24 carry `"agent": "b"`. Each agent's heartbeat runs under its own schedule (`tiny-harness-heartbeat-b-run-…`). No key-shaped string appears in the log |
| 8 | Stop the app (SIGTERM to its PID) | Stopped cleanly |

The TUI step (`tiny-harness tui --url http://127.0.0.1:8090/agents/a`) was replaced by
an A2A client script that sends the same messages. The TUI is unchanged by this work
item, and the client script gives a recordable transcript.
