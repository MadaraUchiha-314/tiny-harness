---
type: evidence
workItem: issue-3
---

# Critic review: tiny-harness: A tiny agent harness! (issue-3)

> The `critic-review` node's proof — a different model/harness reading the diff. Same
> procedure as the self-review round (`reference/reviewing.md`); a round that could not
> run is recorded as **`unavailable`** with the cause and does NOT count toward the
> operator's `reviews.criticReviewCount` (policy: `criticReviewCount: 1`, critic `codex`
> = `codex/gpt-6.1-sol`, timeout 900 s).

The implementation is reviewed at the head of the stacked series (PR #15, branch
`loop/issue-3-l9-demo`, which carries every lower layer). Prompts and envelopes are kept
under `.the-loop/critic/impl-round-*.{md,json}` (not committed).

## Review cycles

| Round | Critic (`<harness>/<model>`) | Outcome | Findings → disposition | Link |
|-------|-----------------------------|---------|------------------------|------|
| 1 | `[codex/gpt-6.1-sol]` | **unavailable** — the round over the whole repository did not finish within its 900 s budget (`THE_LOOP_SERVICE_LOCAL=1 the-loop critic run codex --timeout 900`); no output | — | — |
| 2 | `[codex/gpt-6.1-sol]`, scoped to the trust boundaries, the workflow and the web client, 2026-10-10, 132 s | new findings (8) | 7 will-fix fixed one commit each; 1 split (agent-sourced input framed, a human's own message not) | [PR #15 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/15) |

### Round 2 findings and dispositions

| # | Finding | Disposition |
|---|---------|-------------|
| 1 | An absent participant assertion bypassed task access; intake accepted identity-less messages; the actor was inherited | fixed: not found without `X-Participant-Id`, refused at executor and intake; the harness asserts itself when delegating (`31837ea`, `ad2fef3`) |
| 2 | `Message.metadata` not scrubbed before history | fixed: the whole message is scrubbed (`73b63a4`) |
| 3 | Remote-agent turns recorded unredacted | fixed: scrubbed in the activity (`60eff4b`) |
| 4 | An interrupt could lose an accepted inbox message | fixed: pop after intake, drained state committed (`87ecc59`) |
| 5 | Remote replies, channel messages and A2UI actions entered the context as plain user text | fixed for agent-sourced input (`ad2fef3`); won't-fix for a human participant's own message, which is the task's instruction |
| 6 | Event envelopes had no effect on an existing task | fixed: task envelope applied within the sender's rights, status/artifact envelopes recorded (`5f7b62e`) |
| 7 | The web renderer never subscribed to a task it did not open | fixed: subscription kept open and reopened after each final event; the bridge's replay runs to the newest event; proven live with a second surface |
| 8 | `non_retryable_error_types` had no effect | fixed (`0515312`) |
