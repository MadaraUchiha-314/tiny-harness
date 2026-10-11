---
type: evidence
workItem: issue-19
row: T2
---

# Integration scenarios (T2)

The whole harness completes a task against a scripted OpenAI-compatible server on
loopback, keyless, over both wire APIs, and survives a retryable endpoint failure. Run at
`420df50`.

## Scenarios

`the-loop scenarios --root "$PWD" --glob 'tests/integration/compat/*.py' --glob
'tests/e2e/test_demo_ollama.py' --format markdown`:

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | OpenAI-compatible endpoints | Harness completes a task against an OpenAI-compatible Responses endpoint | docs/specs/issue-19/requirements.md#R3 | tests/integration/compat/test_compat_endpoint.py:68 |
| 2 | OpenAI-compatible endpoints | Harness completes a task against an OpenAI-compatible Chat Completions endpoint | docs/specs/issue-19/requirements.md#R3 | tests/integration/compat/test_compat_endpoint.py:94 |
| 3 | OpenAI-compatible endpoints | A retryable endpoint failure is retried and the task completes | docs/specs/issue-19/requirements.md#R5 | tests/integration/compat/test_compat_endpoint.py:122 |
| 4 | OpenAI-compatible endpoints | Demo completes a task offline against a local Ollama | docs/specs/issue-19/requirements.md#R6 | tests/e2e/test_demo_ollama.py:62 |

Scenario 4 is the e2e row (T4); see [`e2e-ollama.md`](e2e-ollama.md).

## Run

```text
$ env -u OPENAI_API_KEY -u TEMPORAL_API_KEY uv run pytest -v tests/integration/compat
tests/integration/compat/test_compat_endpoint.py::test_harness_completes_a_task_against_a_responses_endpoint PASSED
tests/integration/compat/test_compat_endpoint.py::test_harness_completes_a_task_against_a_chat_completions_endpoint PASSED
tests/integration/compat/test_compat_endpoint.py::test_a_retryable_endpoint_failure_is_retried_and_the_task_completes PASSED
======================== 3 passed, 25 warnings in 3.85s ========================
```

The warnings are the existing `PydanticDeprecatedSince211` notice from
`tiny_harness/service/durable/workflows.py:939`, not introduced here.
