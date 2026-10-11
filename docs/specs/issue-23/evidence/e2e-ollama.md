---
type: evidence
workItem: issue-23
row: T4
---

# End to end against a local Ollama, no push key (T4)

The offline demo (`examples/demo/config.ollama.toml`: embedded Temporal, a loopback
Ollama over Chat Completions) completed a task at `34dccbc` on 2026-10-11 with
`TINY_HARNESS_PUSH_KEY`, `OPENAI_API_KEY` and `TEMPORAL_API_KEY` all absent from the
environment of every process it started. `tests/e2e/demo.py` now **pops**
`TINY_HARNESS_PUSH_KEY` from that environment rather than generating one (R5.3), so the
pass is the proof that nothing needs it (R1.2).

| | |
|---|---|
| Ollama | `ollama serve` on `127.0.0.1:11434` |
| Model | `qwen3:1.7b` (`TINY_HARNESS_OLLAMA_MODEL`); the config's `qwen3:8b` does not fit this machine, as in issue-19's run |
| Temporal | embedded, from the cached CLI |

```text
$ env -u TINY_HARNESS_PUSH_KEY -u OPENAI_API_KEY -u TEMPORAL_API_KEY \
    TINY_HARNESS_OLLAMA_MODEL=qwen3:1.7b uv run pytest tests/e2e/test_demo_ollama.py -s -rs
collected 1 item
tests/e2e/test_demo_ollama.py [   6.3s] task           TASK_STATE_SUBMITTED     <task-id>
[   6.3s] status_update  TASK_STATE_WORKING
[ 382.4s] status_update  TASK_STATE_COMPLETED
.
======================== 1 passed in 384.03s (0:06:24) =========================
```

The 6-minute run time is the 1.7B model on a CPU-only machine, not the harness.
