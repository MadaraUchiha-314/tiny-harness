---
type: evidence
phase: needs-review
workItem: issue-38
---

# Critic review: multi-modal input and output, with a voice mode

> The `critic-review` node's proof. Policy (`the-loop critic policy`): `criticReviewCount: 1`,
> critic `codex` (`codex/gpt-6.1-sol`), run with
> `THE_LOOP_SERVICE_LOCAL=1 the-loop critic run codex --prompt-file … --timeout …`.

## Review cycles

| Round | Critic | Outcome | Findings → disposition | Link |
|-------|--------|---------|------------------------|------|
| 1a | `codex/gpt-6.1-sol` | **unavailable**: one pass over the whole code diff (81 files, 10.7k lines) hit the 900 s limit with no output. Does not count. | none | — |
| 1 | `codex/gpt-6.1-sol` (two passes: server 143 s, 121 k input tokens; client 62 s, 102 k input tokens) | 9 new findings (all major) | GIF frame size unchecked → fixed `76c3e67` · transcript not redacted before Temporal history → `ecd0211` · audio duration understatable in MP4 (bitrate bound cannot cap duration) → duration now counted from what a decoder plays, with codecs restricted per container → `0b2ae57` · retention missed media past 1 000 expired tasks → `b56217c` · web pending speech fetch survived Stop → `15b1b70` · web media had no memory budget → `27abb87` · web PCM read-ahead unbounded → `77cab8a` · media URLs not pinned to the displayed task (both clients) → `09ff49b` · TUI cannot play browser recordings → **won't-fix** (needs a ~30 MB decoder, and no requirement makes the TUI play user recordings; R6.3 *shows* them), with the misleading label fixed → `0788b69`; the owner may ask for PyAV on the PR | [findings](https://github.com/MadaraUchiha-314/tiny-harness/pull/39#issuecomment-6352162571), [replies](https://github.com/MadaraUchiha-314/tiny-harness/pull/39#issuecomment-6352162955) |

The cap of one round was reached; it did not converge to zero. The MP4 duration finding
followed self-review finding 1.5 (fixed with a bitrate bound) with a stronger argument, two
rounds apart rather than consecutively. The fix replaces the heuristic with exact
counting, so it is not escalated as a repeat. After the fixes: 1 315 Python
unit/contract/security/UI tests, 33 media integration tests, 119 web unit tests, 28
strict visual and 8 a11y tests and the real OpenAI e2e test pass.
