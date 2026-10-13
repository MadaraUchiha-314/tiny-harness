---
type: evidence
phase: needs-review
workItem: issue-34
---

# Self-review: show the configured remote agents to the model

> The `self-review` node's proof. Policy (`the-loop critic policy`): `selfReviewCount: 2`,
> stop on no new findings, escalate on a repeated finding.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition | Link |
|-------|----------|---------|------------------------|------|
| 1 | `[claude/claude-opus-5-5]` | new findings | F1: an agent registered at two versions was listed twice in the roster, possibly with a card the delegation does not reach → will-fix, fixed in `399f6b7` (`registered_agents`: one per id at `version="*"`, red→green unit test) | [comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/35#issuecomment-6141121496) |
| 2 | `[claude/claude-opus-5-5]` | new findings | F2: stale `context.py` module docstring (static sections omit `agents`) → will-fix, fixed in `3fc7011` | [comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/35#issuecomment-6141145321) |

Two rounds is the operator's cap, so the loop stops here, not on convergence. Round 2
found only a docstring nit and no repeat of F1. The critic round follows.
