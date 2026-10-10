---
type: evidence
workItem: issue-19
---

# Final validation: Support connecting to any OpenAI-compatible API

Summarised from [testing-plan.md § Verification results](../testing-plan.md#verification-results)
and the review records. The plan's activities ran at `420df50`. After the review fixes,
the unit, contract and compat suites were re-run at `9a3b439` with `OPENAI_API_KEY` and
`TEMPORAL_API_KEY` unset: 387 passed.

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| R1.1–R1.2 every request goes to `base_url` and nowhere else; no `base_url` keeps `https://api.openai.com/v1` | unit tests on the client's base URL and on refused redirects; the compat scenarios hit only the loopback fake server, and pass inside a loopback-only network namespace | [unit.md](unit.md), [integration.md](integration.md), [security.md](security.md) |
| R1.3 `OPENAI_BASE_URL` is ignored | an abuse-case test with the variable pointing elsewhere; a startup WARNING names the variable, never its value | [security.md](security.md), [unit.md](unit.md) |
| R1.4 a non-absolute or non-`http(s)` `base_url` exits 2 naming `openai.base_url` | config tests, including `https:example.com` (critic finding 3, `1698416`) | [unit.md](unit.md), [critic-review.md](critic-review.md) |
| R1.5 the model name is passed verbatim | adapter tests; the real Ollama run with `qwen3:1.7b` | [unit.md](unit.md), [e2e-ollama.md](e2e-ollama.md) |
| R2.1–R2.3 key required without `base_url`; keyless with it, no `Authorization` header; key sent as bearer when set | config tests; header tests against the recorded request; the compat scenarios ran keyless | [unit.md](unit.md), [integration.md](integration.md) |
| R3.1–R3.2 `api` is `responses` (default) or `chat_completions`, anything else exits 2; Responses requests unchanged | config tests; the unchanged OpenAI unit suite and contract snapshots | [unit.md](unit.md), [contract.md](contract.md) |
| R3.3–R3.4 Chat Completions: system prompt, turns, tools, tool calls and results, streaming, structured output, usage, finish reasons; absent fields read as zero | recorded-body tests in `test_openai_chat.py`; a compat scenario per wire API; the real Ollama run completed over Chat Completions | [unit.md](unit.md), [integration.md](integration.md), [e2e-ollama.md](e2e-ollama.md) |
| R4.1–R4.3 `context_window_tokens` overrides the table, the default is unchanged, a non-positive or non-integer value exits 2 | config and adapter tests, including `true` (critic finding 4, `ac8a0a5`) | [unit.md](unit.md) |
| R5.1–R5.3 429/5xx/timeout/refused are retryable; other statuses are `ProviderError`; an unparseable 2xx is `ProviderError` | malformed-body tests on both wire APIs, including deeply nested JSON and a stream with no `finish_reason` (`538cd01`, `072ba9f`); a 503 that durable execution retries | [unit.md](unit.md), [integration.md](integration.md) |
| R6.1–R6.3 the shipped Ollama config completes a task offline; documented | the e2e run on Ollama 0.40.2 reached `COMPLETED` in 106.5 s with no key; the TUI walkthrough reached `COMPLETED`; README and getting-started updated; docs build passes | [e2e-ollama.md](e2e-ollama.md), [manual.md](manual.md), [documentation.md](documentation.md) |
| NFR backwards compatibility | contract snapshots are additive only, apart from `api_key` becoming optional; CI suites and UI snapshots unchanged | [contract.md](contract.md), [regression.md](regression.md) |
| NFR observability | the `model endpoint` log line and the chat span's `server.address`, `server.port` and `tiny_harness.llm.api` are tested, and were seen in the real run | [unit.md](unit.md), [e2e-ollama.md](e2e-ollama.md) |
| NFR no new runtime dependency | `git diff --stat 755ccb6 -- pyproject.toml uv.lock` is empty | this PR's diff |
| Security abuse cases 1–5 | each one maps to a passing negative test (22 in all); the security-review skill reported no findings; the human signed off (tier 4) | [security.md](security.md), [security-review.md](security-review.md) |

Reviews: [self-review](self-review.md) (2 rounds, 5 findings fixed),
[critic-review](critic-review.md) (`codex/gpt-6.1-sol`, 4 findings fixed),
[security-review](security-review.md) (no findings; signed off by @MadaraUchiha-314).

One stated limit: the real local model, a 1.7B model sized to this machine, answered
without calling tools. Tool calls over Chat Completions are therefore proved by the
recorded-body tests and the compat scenarios, not by the live model.
