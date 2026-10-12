---
type: evidence
phase: needs-review
workItem: issue-27
---

# Critic review: Remote sub-tasks hear remote state changes between turns

> The `critic-review` node's proof. The operator's policy (`the-loop critic policy`) is 1
> critic round. The configured critic is `codex` (`gpt-6.1-sol`).

## Review cycles

| Round | Critic | Outcome | Findings → disposition | Duration | Link |
|-------|--------|---------|------------------------|----------|------|
| 1 | `[codex/gpt-6.1-sol]` | new findings | 3 findings, all will-fix: (1, high) a push token could reach exported traces through the SDK's span exception recording; (2, med) a reply asserted the replying human's id instead of the harness's; (3, med) a rollover dropped a pending recheck | 92.7 s | [PR comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/28#issuecomment-6133584585) |

All three were fixed in one commit. Each fix has a test, and the reply test was confirmed
red without its fix. The policy's single critic round is spent, so no second critic
round ran. The fixes were checked by the suite (156 affected tests three times in a row,
and the full suite) and by the security review.
