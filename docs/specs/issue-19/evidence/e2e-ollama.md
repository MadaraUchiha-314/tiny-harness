---
type: evidence
workItem: issue-19
row: T4
---

# End to end against a real Ollama (T4)

The demo, configured as `examples/demo/config.ollama.toml` (embedded Temporal, a
loopback Ollama over Chat Completions), completed a task with neither `OPENAI_API_KEY`
nor `TEMPORAL_API_KEY` in its environment. Run at `420df50` on 2026-10-10.

## Environment

| | |
|---|---|
| Ollama | 0.40.2, Linux release archive in a user-local directory, `ollama serve` on `127.0.0.1:11434` with `OLLAMA_CONTEXT_LENGTH=16384`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0` (to fit the machine's free memory) |
| Model | `qwen3:1.7b` (`TINY_HARNESS_OLLAMA_MODEL`): the demo config's `qwen3:8b` does not fit this machine (4 CPUs, 7 GB RAM, no GPU) |
| Temporal | embedded, from the cached CLI |

## Configuration the test wrote

```toml
[temporal]
mode = "embedded"
task_queue = "tiny-harness-e2e-f1db28a4"
search_attributes = false
[openai]
base_url = "http://127.0.0.1:11434/v1"
api = "chat_completions"
model = "qwen3:1.7b"
context_window_tokens = 16384
timeout = "PT600S"
max_output_tokens = 2000
```

## Run

```text
$ env -u OPENAI_API_KEY -u TEMPORAL_API_KEY TINY_HARNESS_OLLAMA_MODEL=qwen3:1.7b \
    uv run pytest tests/e2e -k ollama -s -rs
collected 5 items / 4 deselected / 1 selected

tests/e2e/test_demo_ollama.py [   6.2s] task           TASK_STATE_SUBMITTED     6a473b84-b01a-47d7-8e1a-f69acfaec078
[   6.2s] status_update  TASK_STATE_WORKING
[ 106.5s] status_update  TASK_STATE_COMPLETED
.

================= 1 passed, 4 deselected in 110.06s (0:01:50) ==================
```

## Server log: the endpoint line

```json
{"level": "INFO", "logger": "tiny_harness.runtime", "msg": "model endpoint http://127.0.0.1:11434 api=chat_completions model=qwen3:1.7b", "ts": "2026-10-10T20:18:19.539438+00:00"}
```

## Trace: the chat span

```json
{
  "name": "chat qwen3:1.7b",
  "attributes": {
    "gen_ai.operation.name": "chat",
    "gen_ai.provider.name": "tiny_harness",
    "gen_ai.request.tools": 17,
    "server.address": "127.0.0.1",
    "server.port": 11434,
    "tiny_harness.llm.api": "chat_completions",
    "gen_ai.request.model": "qwen3:1.7b",
    "gen_ai.response.model": "qwen3:1.7b",
    "gen_ai.usage.input_tokens": 2032,
    "gen_ai.usage.output_tokens": 290,
    "gen_ai.usage.cache_read.input_tokens": 0,
    "gen_ai.response.finish_reasons": "stop",
    "gen_ai.response.tool_calls": 0
  }
}
```

## What this run does and does not show

- It shows the real wire path: Ollama accepted the Chat Completions request with the
  harness's 17 tool definitions, returned usage the adapter mapped, and the task ran to
  `COMPLETED` through the embedded worker with no key of either kind.
- The 1.7B model answered the complaint in **one turn without calling a tool**, so the
  demo's tool path (`get_order`, the confirm card) was not exercised against a real local
  model here. Tool calls over Chat Completions are proved by the recorded-body unit tests
  and the streaming assembly test (T1); a larger model on capable hardware is what the
  demo config's `qwen3:8b` default is for.
- The run had network access; the **offline** claim is proved separately by T8's
  loopback-only namespace run ([`security.md`](security.md)).
