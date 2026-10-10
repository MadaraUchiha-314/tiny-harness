---
type: evidence
phase: needs-review
workItem: issue-20
---

# Self-review: issue-20

Work item: issue-20 · node `self-review` · reviewer `claude/opus-5.5` (the running
harness) · policy from `the-loop critic policy`: `selfReviewCount: 2`,
`stopOnNoNewFindings: true`, `escalateOnRepeatFinding: true`.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition → commit | Link |
|---|---|---|---|---|
| 1 | `claude/opus-5.5` | 3 new findings | (1) correctness/medium: a non-ASCII id reaches the server latin-1 decoded in `X-Participant-Id`, so header-only calls (subscribe, cancel) miss the task the metadata created, and a CR/LF breaks HTTP → will-fix → `2adbe39` (R1.8: printable ASCII only, exit 2); (2) readability/low: `args.participant` rewritten and re-cast → won't-fix, matches `str(args.task_id)`; (3) typing/low: `Callable[..., …]` cast → won't-fix, deliberate lazy import, both call sites tested | [findings](https://github.com/MadaraUchiha-314/tiny-harness/pull/21#issuecomment-6100986021) |
| 2 | `claude/opus-5.5` | 2 new findings, none repeated | (1) docs/low: `--participant` help omits the ASCII rule → will-fix → `38637b4`; (2) evidence/low: unit and walkthrough records predate `2adbe39` → will-fix, re-run and refreshed. Checked, not a finding: `getuser()` honours `LOGNAME`/`USER`, which is consistent with a self-asserted id (decision-003) | [findings](https://github.com/MadaraUchiha-314/tiny-harness/pull/21#issuecomment-6101001255) |

The cap of 2 rounds was reached; no finding recurred, so no escalation was triggered.
