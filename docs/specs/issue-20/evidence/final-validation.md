---
type: evidence
workItem: issue-20
---

# Final validation: `tiny-harness tui` never asserts a participant

Summarised from [testing-plan.md § Verification results](../testing-plan.md#verification-results)
and the review records, at the head of PR #21.

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| R1.1 `--participant` accepted | parser unit test | [unit.md](unit.md) |
| R1.2 every message and action asserts the id (header + metadata) | real `run_tui` → `SdkClient.connect` against an embedded harness reaches `COMPLETED`; demo shows `alice  reporter` | [integration.md](integration.md), [manual-walkthrough.md](manual-walkthrough.md) |
| R1.3 OS user name by default, stripped | unit tests (`getuser` patched, including `" alice "`); demo shows `[os-user]  reporter` | [unit.md](unit.md), [manual-walkthrough.md](manual-walkthrough.md) |
| R1.4 no OS user → exit 2 naming `--participant` | unit test with `getuser` raising `OSError` (not staged on the host) | [unit.md](unit.md) |
| R1.5 blank `--participant` → exit 2 | unit tests (empty, spaces); demo with `'  '` | [unit.md](unit.md), [manual-walkthrough.md](manual-walkthrough.md) |
| R1.6 both paths (`--url` and embedded hosting) | unit test on the `--url` path; integration scenarios on the embedded path; demo on both | [unit.md](unit.md), [integration.md](integration.md), [manual-walkthrough.md](manual-walkthrough.md) |
| R1.7 the TUI shows the asserted id | composer reads `Enter to send as alice` in the regression scenario; snapshots differ from `main` only there | [integration.md](integration.md), [regression.md](regression.md) |
| R1.8 non-printable-ASCII id → exit 2 | unit tests (`josé`, CR, LF, tab, CJK, from flag and OS); demo with `josé` | [unit.md](unit.md), [manual-walkthrough.md](manual-walkthrough.md) |
| R2.1 regression test red before, green after | red: `InvalidParamsError('no participant asserted')` through the real `run_tui`; green at head | [integration.md](integration.md) |
| R2.2 embedded scenario takes the id from the command | stand-in now receives `participant` from `commands.tui` | [integration.md](integration.md) |
| Security considerations, abuse cases 1–2 | server refusal and access tests unchanged and passing; security-review skill: no findings | [regression.md](regression.md), [security-review.md](security-review.md) |

Reviews: [self-review](self-review.md) (2 rounds, 3 findings fixed, 2 won't-fix with
reasons), [critic-review](critic-review.md) (`codex/gpt-6.1-sol`; the first round timed
out, and the retry's one finding was fixed), [security-review](security-review.md)
(pass, tier 3). The full CI suite had one failure in the untouched observability test
on the first run and passed on the second. That is a pre-existing flake, recorded in
[regression.md](regression.md).
