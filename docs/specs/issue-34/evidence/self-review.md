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

## Review of R5–R7 (after PR review)

The rounds above covered R1–R4, at `7cb2103`. R5 (`[card]`), R6 (the example) and R7
(every child over A2A) came later from PR review, with 16 commits and about 650 lines of
production code. Round 3 reviewed `git diff 7cb2103..HEAD -- tiny_harness`.

| Round | Reviewer | Outcome | Findings → disposition |
|-------|----------|---------|------------------------|
| 3 | `[claude/claude-opus-5-5]` | new findings | **SR-1** — replay determinism: an in-flight parent that spawned a child under the old code would, on replay, meet `start_agent_task` where its history has `StartChildWorkflowExecution` (the same for `/sub-task` and the new completion shortcut), and the workflow task would fail. The codebase has never used `workflow.patched`. → **escalated**: patch the changed sequences or document "finish or cancel in-flight tasks with sub-tasks before upgrading"; a decision for the reviewer. **SR-2** — a briefed `model` skipped the selectable-models check that `/model` applies → will-fix, fixed in `fe0587d` (`check_model`). **SR-3** — behaviour change for outside clients: a first message that is only a task envelope now starts the task without a model turn (it used to run a turn on a synthetic "[task updated…]" text) → accepted, recorded in the `a2a-server` capability doc. **SR-4** — a parent cancelled while `start_agent_task` is in flight can leave the created child without a stand-in, so the cancel does not reach it → accepted as a narrow residual; noted for a follow-up. **SR-5** — the completion shortcut that waits for an unread result skips the `task.complete` hook for that one turn → accepted: the task does not complete in that turn, and the hook runs at the next completion. |

Found and fixed during R7's verification and CI healing, before this round:

- a follow read replayed history as change (`2dba276`);
- agent streams left open (`2dba276`);
- a delegated parent completing without reading a result (`2dba276`);
- a stuck new stand-in (`74ff83b`);
- a cancel mid-delivery failing the workflow (`92ffab1`);
- a child's signal before a continued run's load (`3104ea1`).
