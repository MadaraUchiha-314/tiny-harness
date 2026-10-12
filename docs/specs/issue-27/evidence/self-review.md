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
