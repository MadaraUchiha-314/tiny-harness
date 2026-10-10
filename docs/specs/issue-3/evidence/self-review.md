---
type: evidence
phase: needs-review
workItem: "github:MadaraUchiha-314/tiny-harness#3"
---

# Self-review: tiny-harness: A tiny agent harness! (issue-3)

> The `self-review` node's proof. One row per round, per `reference/reviewing.md`:
> attribution prefix, own-comment marker, reply-first-then-fix, stop on zero new
> findings, escalate on a repeated finding. Outcome is one of: new findings ·
> zero (converged) · escalated · **unavailable**. Policy (`the-loop critic policy`):
> `selfReviewCount: 2`, `criticReviewCount: 1`, stop on no new findings.

The series is reviewed at its head: PR #15 (Layer 9) carries every lower layer merged
forward, so a round over `fad9da8..HEAD` plus the stacked PRs' own review threads covers
the whole work item.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition | Link |
|-------|----------|---------|------------------------|------|
| 1 | `[claude/fable-5.1]`, fresh context, 2026-10-10 | new findings (10) | 10 will-fix, fixed in `c61a10d`: wire-name length cap (64), CRLF carry in the SSE parser (parser since replaced by `@a2a-js/sdk`), vacuous `<= 1` ledger assertions tightened, all worker logs scanned for secrets, secret list from `config.SECRET_VARIABLES`, push key generated for the e2e run, four doc corrections (hooks catalogue, activity names, `[anthropic]` shape, MCP default environment), two wording fixes. Deviation: one commit for the round instead of one per finding. | [PR #15 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/15) |
| 2 | `[claude/fable-5.1]`, fresh context, 2026-10-10 | new findings (10 + CI) | 9 will-fix fixed in `0aac059` (stream deadline and read timeout, fixtures start inside `try`, log handles and zombie reaping, registry name in tool descriptions, three doc path/wording corrections, 12 intrinsics listed, e2e ordering and chaos cancellation, CI runs contract/security/UI, pyright covers `examples/`); finding 1 (stale evidence) closed by rerunning every suite at the final head and regenerating `unit.md`, `e2e.md`, `crash-recovery.md`. Cap of 2 self-reviews reached. | [PR #15 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/15) |
