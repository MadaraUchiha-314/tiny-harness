---
type: evidence
workItem: issue-25
---

# Self-review: Make the CLI/TUI experience seamless

The policy (`the-loop critic policy`): `selfReviewCount: 2`, `stopOnNoNewFindings: true`
and `escalateOnRepeatFinding: true`.

## Self-review

| Round | Reviewer | Scope | Outcome | Link |
|-------|----------|-------|---------|------|
| 1 | `claude-code/claude-opus-5-5` (the session) | `workflows.py` (intake, dispatch, commands, completion, children), `a2a/handler.py`, `a2a/bridge.py`, `a2a/executor.py` identity | One new finding (high), fixed | `10563b4` |
| 2 | `claude-code/claude-opus-5-5` (the session) | `harness/commands/builtins.py` (parsing, the allowlist, the role policy), `home.py` (safe creation) | Two new findings (both low): one escalated, one won't-fix with a reason | [security-review.md](security-review.md) S2, S3 |

### Findings

| # | Round | Finding | Severity | Disposition |
|---|-------|---------|----------|-------------|
| 1 | 1 | A message's metadata `participant_id` overrode the request's `X-Participant-Id`, so a watcher could act as the reporter (complete, `/model`, `/effort`, `/sub-task`) | high | **Fixed** in `10563b4`: `sender_of` makes the request's assertion decide and refuses a mismatch. The test failed before the fix and passes after it |
| 2 | 2 | Watchers are restricted only for the built-in commands that change the task; a plugin command runs for a watcher | low | **Escalated:** the spec lists only the built-ins, so whether plugin commands should default to "no watchers" is the human's call. See the PR briefing |
| 3 | 2 | An existing `~/.tiny-harness` that is wider than `0700` is not narrowed | low | **Won't fix:** it is the user's own directory, and symlinks and foreign owners are refused. Reason recorded in `security-review.md` S3 |

Checked in round 1 and found sound:

- A participant's `/sub-task` history note is folded during the same intake and starts
  no turn.
- A refused completion parks the task again instead of leaving it `WORKING`.
- `_finish` tolerates a closed parent.
- The control path runs the validator before the interrupt.
- `SubscribeToTask` follows until a terminal state and ends at one.

Checked in round 2 and found sound:

- `/model` and `/effort` don't echo a refused value.
- `/sub-task` stores its text only as a goal.
- `home.py` holds the directory open with `O_DIRECTORY|O_NOFOLLOW`, checks the owner on
  that handle, and creates the file with `O_EXCL|O_NOFOLLOW` at `0600`. Losing a
  creation race is re-checked.
