---
type: evidence
workItem: issue-19
row: T1
---

# Unit tests (T1)

All unit tests pass at `420df50`, with `OPENAI_API_KEY` and `TEMPORAL_API_KEY` unset:
342 passed, 84 of them new for this work item.

## Full unit suite

```text
$ env -u OPENAI_API_KEY -u TEMPORAL_API_KEY uv run pytest tests/unit -q
342 passed in 4.35s
```

## The work item's unit tests

```text
$ env -u OPENAI_API_KEY -u TEMPORAL_API_KEY uv run pytest -v \
    tests/unit/test_config_openai.py tests/unit/models/test_openai_endpoint.py \
    tests/unit/models/test_openai_malformed.py tests/unit/models/test_openai_chat.py \
    tests/unit/service/test_runtime_model.py tests/unit/service/test_o11y.py \
    tests/unit/test_e2e_ollama_guard.py
============================== 84 passed in 3.02s ==============================
```

| File | What it proves | Requirement |
|------|----------------|-------------|
| `tests/unit/test_config_openai.py` | `base_url` / `api` / `context_window_tokens` validation, the key rule, abuse cases 2–3, the redactor's input, the shipped Ollama config loads keyless | R1.4, R2, R3.1, R4.3, R6.1 |
| `tests/unit/models/test_openai_endpoint.py` | the URL a request reaches, `OPENAI_BASE_URL` ignored, verbatim model, keyless and keyed headers, org/project suppression, redirect refused, model info | R1.1–R1.3, R1.5, R2.2–R2.3, R4.1–R4.2 |
| `tests/unit/models/test_openai_malformed.py` | unparseable Responses bodies (invoke and stream) → `ProviderError` | R5.3 |
| `tests/unit/models/test_openai_chat.py` | Chat Completions mapping, parsing, finish rule, absent fields, streaming assembly, errors | R3.2–R3.4, R5 |
| `tests/unit/service/test_runtime_model.py` | the startup line's shape; origin drops path and query; a translated error carries no key | NFR observability, abuse case 5 |
| `tests/unit/service/test_o11y.py` | the chat span's `server.address`, `server.port`, `tiny_harness.llm.api` | NFR observability |
| `tests/unit/test_e2e_ollama_guard.py` | the Ollama e2e skips with a reason, never passes silently | T4 |

Each task's red→green transition is recorded in its commit message (`6cead4e`,
`222cd46`, `1879361`, `bd17981`, `420df50`).
