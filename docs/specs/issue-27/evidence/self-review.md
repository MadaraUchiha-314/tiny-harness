---
type: evidence
phase: needs-review
workItem: issue-27
---

# Self-review: Remote sub-tasks hear remote state changes between turns

> The `self-review` node's proof. One row per round, per `reference/reviewing.md`.
> The operator's policy (`the-loop critic policy`) is 2 self rounds and 1 critic round,
> stopping on a round with no new findings and escalating on a repeat.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition | Link |
|-------|----------|---------|------------------------|------|
| 1 | `[claude/claude-opus-5-5]` (a fresh-context sub-agent, read-only) | new findings | 9 code findings and 5 test gaps. Will fix: 1–7, 9 and the test gaps. Won't fix: 8 (refusal timing; ids are not secret, recorded in requirements) | [PR comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/28#issuecomment-6133257291) |
| 2 | `[claude/claude-opus-5-5]` (a fresh-context sub-agent, read-only, told round 1's findings) | new findings | 4 findings, all will-fix: (1) an `IndexError` after a failed fetch on the last recheck; (2) a cancel lost across a rollover; (3) a stale claim from a push during a turn; (4) the no-spin test could not tell the fix from the bug. Fixing the test gaps (`follow_remote_task` unit tests) also showed that a missing agent was retryable, which defeated round 1's fix 3; it is now non-retryable. | [PR comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/28#issuecomment-6133408620) |

Round 2 was the last self round the operator's policy allows (`selfReviewCount: 2`), so
the review moved to the critic with round 2's fixes applied. Each round's fixes were
committed together (921f679 for round 1, and the round-2 commit), not one commit per
finding: the fixes touched the same functions. The PR comments carry the per-finding
dispositions.
