---
type: evidence
workItem: issue-36
---

# Critic review: mount tiny-harness agents onto an existing FastAPI or Starlette app

> The `critic-review` node's proof. Policy (`the-loop critic policy`):
> `criticReviewCount: 1`, critic `codex` (`gpt-6.1-sol`, timeout 900 s). Run in-process
> with `THE_LOOP_SERVICE_LOCAL=1 the-loop critic run codex …`.

## Review cycles

| Round | Critic (`<harness>/<model>`) | Outcome | Findings → disposition | Link |
|-------|-----------------------------|---------|------------------------|------|
| 1 (first attempt) | `codex/gpt-6.1-sol` | **unavailable**: the round hit the 900 s limit with no output (`codex did not finish (ran 900s…)`). The prompt named a broad diff (`tiny_harness tests examples …`). It does not count | — | — |
| 1 | `codex/gpt-6.1-sol` | 2 new findings (medium), 85.5 s. Prompt limited to the nine core source files and the spec chain's security sections, with every self-review finding listed | Both **will-fix**, fixed: #1 a non-default agent's plugin data root is `plugin-data-<id>`, so two agents whose stores share a folder do not share plugin data (`f915eaf`) · #2 an acquire during the pool's last shutdown waits for it, so no second dev server opens on a file that is still locked (`ceaab2b`) | [PR #37 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/37#issuecomment-6157985822) |

**Stop condition:** the round cap (`criticReviewCount: 1`) was reached. No finding repeats
an earlier one.
