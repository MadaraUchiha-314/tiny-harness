---
type: evidence
workItem: issue-17
---

# Critic review: Support embedded Temporal mode

Work item: issue-17 · node `critic-review` · policy from `the-loop critic policy`:
`criticReviewCount: 1`, `stopOnNoNewFindings: true`, `escalateOnRepeatFinding: true`.
Critic from `the-loop critic list`: `codex` (`codex` harness, `gpt-6.1-sol`), available.

## Review cycles

| Round | Critic (`<harness>/<model>`) | Outcome | Findings → disposition | Link |
|-------|-----------------------------|---------|------------------------|------|
| 1 | `codex/gpt-6.1-sol` | 2 new findings; ran ok in 68.5 s (55,278 input / 2,040 output tokens, 430,208 cache-read) | (1) high: the programmatic `serve()` did not install the SIGTERM handler, so uvicorn re-raised SIGTERM with the default action and the embedded dev server could be orphaned → will-fix → `f037412` (shared `service/signals.py`; regression scenario *Embedded server stops when a program running serve receives SIGTERM*, red: process never exited → green); (2) medium: the download directory was prepared even with a pinned `binary_path` → will-fix → `dedeb0c` (red → green) | [findings and replies](https://github.com/MadaraUchiha-314/tiny-harness/pull/18#issuecomment-6100414668) |

The cap of 1 round was reached. The critic's prompt listed the seven findings already raised
and the four accepted deviations from design.md, and neither was repeated. Regression after
both fixes: tests/unit 246 passed; integration, contract, security and ui 113 passed.

Invocation: `THE_LOOP_SERVICE_LOCAL=1 the-loop critic run codex --root "$PWD" --cwd "$PWD"
--prompt-file <prompt> --work-item issue-17 --timeout 900`. The critic ran read-only and
changed no files.
