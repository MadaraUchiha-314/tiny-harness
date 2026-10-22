---
type: evidence
workItem: issue-38
---

# Design critic review: multi-modal input and output, with a voice mode

> The work item selected the opt-in `design-critic-review` phase. A different model read
> `design.md` against `requirements.md` before the testing plan was derived from it.

## Design critic review

| Round | Critic (`<harness>/<model>`) | Outcome | Findings → disposition | Link |
|-------|-----------------------------|---------|------------------------|------|
| 1 | `codex/gpt-6.1-sol` | 10 new findings (2 blocker, 8 major); all verified against the code and fixed in `design.md` | 1 speech artifact after the final status → will-fix `7f747ac` · 2 speech URL before the object exists → will-fix `0bf7679` · 3 retries rewrite a file a reader is following → will-fix `4392653` · 4 speech jobs lost at rollover → will-fix `281c995` · 5 `control` bypasses media intake → will-fix `ed2ab45` · 6 compressed-audio duration not enforced → will-fix `fcebfcc` · 7 native-audio budget, media descriptions in compaction → will-fix `0393279` · 8 TUI cache path from file name → will-fix `785bf4f` · 9 output modalities, card advertises unusable audio → will-fix `e336b61` · 10 late microphone grant → will-fix `a1b1071` | [findings](https://github.com/MadaraUchiha-314/tiny-harness/pull/39#issuecomment-6344814314), [replies](https://github.com/MadaraUchiha-314/tiny-harness/pull/39#issuecomment-6344818048) |

The round ran in 70 s (65 529 input tokens, 2 182 output tokens) with
`THE_LOOP_SERVICE_LOCAL=1 the-loop critic run codex --prompt-file … --timeout 900`. The
operator's policy (`the-loop critic policy`) is `criticReviewCount: 1`, so no second
round ran. The cap was reached, not convergence. The fixes are reviewed by the human at
`design-approval` together with the testing plan.
