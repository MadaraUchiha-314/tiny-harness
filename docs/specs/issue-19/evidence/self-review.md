---
type: evidence
phase: needs-review
workItem: issue-19
---

# Self-review: Support connecting to any OpenAI-compatible API

Two rounds, the operator's cap (`the-loop critic policy`: `selfReviewCount: 2`). Five
findings, all will-fix, each fixed in its own commit; none recurred. Round 2 found only
documentation, so the code converged after round 1.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition | Link |
|-------|----------|---------|------------------------|------|
| 1 | `claude/claude-opus-5-5` | new findings (3) | (1) docs ran `ollama pull` before `ollama serve` → fixed `95dde18`; (2) an exported `OPENAI_BASE_URL` was ignored silently → startup WARNING without the value, tested, `c57e026`; (3) `design.md` named a `_parse_failure` wrapper that does not exist → corrected `65c27b8` | [PR #22 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/22#issuecomment-6101826518) |
| 2 | `claude/claude-opus-5-5` | new findings (2, docs only) | (1) README's model list said OpenAI only → `974d1da`; (2) architecture index described the e2e tier as Cloud + OpenAI only → `81cbd95` | [PR #22 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/22#issuecomment-6101843645) |

## Considered and not raised

- **Proxy environment variables.** The SDK's HTTP client honours `HTTP(S)_PROXY`, so a
  configured proxy also carries requests to a custom endpoint. That is an operator's
  deliberate network choice, not the ambient redirect R1.3 forbids, and it is unchanged
  from today.
- **Parse errors from the harness's own code.** `PARSE_ERRORS` would also label a
  `TypeError` from a bug in the mapping as an unparseable response. It surfaces as a
  non-retryable `ProviderError` naming the exception type, so it is visible rather than
  retried forever; accepted.
