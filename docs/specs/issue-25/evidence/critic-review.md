---
type: evidence
workItem: issue-25
---

# Critic review: Make the CLI/TUI experience seamless

The policy (`the-loop critic policy`): `criticReviewCount: 1`, `stopOnNoNewFindings: true`
and `escalateOnRepeatFinding: true`. The only critic configured is `codex`.

## Review cycles

| Round | Critic (`<harness>/<model>`) | Outcome | Findings → disposition | Link |
|-------|-----------------------------|---------|------------------------|------|
| 1 (attempt 1) | `[codex/gpt-6.1-sol]` | **unavailable**: timed out at 900 s with no output; the whole product diff was one scope | — | — |
| 1 (attempt 2) | `[codex/gpt-6.1-sol]` | **unavailable**: three scoped prompts, each timed out at 900 s with no output | — | — |
| 1 | `[codex/gpt-6.1-sol]` | **10 new findings** (2 high, 8 medium): 9 fixed, 1 won't-fix with a reason | see the table below | [PR #26 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/26#issuecomment-6120100901) |

- **How round 1 ran.** It was three scoped prompts run in parallel, in-process
  (`THE_LOOP_SERVICE_LOCAL=1`), with `--timeout 2400`:
  - A: the workflow, 191 s, 75,982 input and 4,568 output tokens.
  - B: the A2A path, 90 s, 61,542 input and 2,188 output tokens.
  - C: commands, the plugin loader and `home.py`, 119 s, 52,280 input and
    2,094 output tokens.
- **Why the earlier attempts don't count.** A one-word ping answered in 6 s, so the
  harness itself worked; those attempts simply needed more than the configured 900 s.
  They are recorded as unavailable and do not count as passing rounds.

### Findings and dispositions

| # | Finding | Severity | Disposition → commit |
|---|---------|----------|----------------------|
| A1 | `workflows.py`: an interrupt that cut the turn also cut a command it was running, after its message was consumed | high | **fixed** `8867c0c`: the command runs under `asyncio.shield`, and `_await_runner` finishes it. A follow-on gap is closed with `unanswered`, carried across continue-as-new |
| A2 | `workflows.py`: a refused completion left ordinary messages taken in the same intake unanswered | medium | **fixed** `ead3fb6` |
| A3 | `workflows.py`: a later `interrupt=false` cleared a completion's interrupt | medium | **fixed** `1183707` |
| A4 | `workflows.py`: `history_notes` were not carried across continue-as-new | medium | **fixed** `8867c0c` (`_fold_history_notes` runs before every rollover) |
| B1 | `handler.py`: a non-streaming Complete could answer with the previous state | medium | **fixed** `6ba4203` (the answer carries the last status the stream delivered) |
| B2 | `executor.py`: a duplicate control waited forever | medium | **fixed** `b92ba7a` |
| B3 | `executor.py`: cancel authorizes against a snapshot, so a role removed mid-request still cancels | medium | **won't fix**: every operation is authorized at request time, and the window is one RPC. Rechecking in the workflow would need the cancel signal to carry an identity, an A2A contract change outside #25 |
| C1 | `loader.py`: an invalid `commands.json` left its command hooks registered unfiltered | high | **fixed** `1e6a561` (fails closed) |
| C2 | `home.py`: `config.toml` was visible before it was written | medium | **fixed** `f3e4809` (written to a temporary file, then hard-linked into place) |
| C3 | `home.py`: `chmod` by path could follow a swapped-in symlink | medium | **fixed** `f3e4809` (`fchmod` on the `O_NOFOLLOW` handle) |

Each fix has a regression test that failed before the fix, except B1. B1 is a timing
race, so its test guards the behaviour rather than reproducing the race. After the fixes,
all 742 tests in `unit`, `contract`, `security`, `ui` and `integration` pass.
