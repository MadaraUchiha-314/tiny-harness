---
type: evidence
phase: needs-review
workItem: issue-19
---

# Critic review: Support connecting to any OpenAI-compatible API

One round, the operator's cap (`the-loop critic policy`: `criticReviewCount: 1`), with
the one configured critic, `codex` (`gpt-6.1-sol`). It raised four findings, all valid,
each fixed in its own commit with a red→green test. The round hit the cap rather than
converging on zero findings; every finding is fixed and none was raised twice.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition | Link |
|-------|----------|---------|------------------------|------|
| 1 | `codex/gpt-6.1-sol` (`the-loop critic run codex`, 115 s; 60 087 input / 3 491 output tokens, 657 920 cache-read) | new findings (4) | (1) deeply nested JSON raised `RecursionError`, which escaped the parse mapping → added to `PARSE_ERRORS`, `538cd01`; (2) an empty or cut-off Chat Completions stream became a successful empty `STOP` → a stream without a `finish_reason` is a `ProviderError` and emits nothing, `072ba9f`; (3) `HttpUrl` normalized `https:example.com` into an absolute URL → the raw value must start with `http(s)://` and a host, `1698416`; (4) `context_window_tokens = true` was coerced to 1 → `StrictInt`, `gt=0`, `ac8a0a5` | [PR #22 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/22#issuecomment-6101868515) |

## Prompt

The critic read the repository at `81cbd95` with `git diff 755ccb6..HEAD`, the spec
chain in `docs/specs/issue-19/`, and the self-review findings already raised (so it would
add rather than repeat). Its output contract: findings only, most severe first, each
with `file:line`, the requirement or abuse case it violates, and a fix.
