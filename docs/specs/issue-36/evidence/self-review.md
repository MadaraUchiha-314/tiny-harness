---
type: evidence
phase: needs-review
workItem: issue-36
---

# Self-review: mount tiny-harness agents onto an existing FastAPI or Starlette app

> The `self-review` node's proof, per `reference/reviewing.md`. Policy (`the-loop critic
> policy`): `selfReviewCount: 2`, `stopOnNoNewFindings: true`,
> `escalateOnRepeatFinding: true`. Each round is a fresh-context reviewer on the same
> harness and model, `[claude/opus-5.5]`, given the diff, the spec chain and the
> findings already raised.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition | Link |
|-------|----------|---------|------------------------|------|
| 1 | `[claude/opus-5.5]` | 7 new findings (1 medium, 6 low). None let one agent reach another's task | All **will-fix**, all fixed, one commit each: #1 pool waiter cancellation leak (`276a814`) · #2 namespace in the embedded pool key and the claim (`f71ad44`) · #3 unsafe `context_id` lists nothing, escaping covers `\` (`2d2b917`) · #4 a failing resolver gives a generic error, not its text (`4fe283c`) · #5 only harnesses of this process get unfetched cards (in the issue-34 reconciliation, `1d783d3`) · #6 exact mount check (`7f6122e`, `98f6df2`) · #7 FastAPI gate resets `CURRENT_AGENT` (`98f6df2`) | [PR #37 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/37#issuecomment-6157427468) |
| 2 | `[claude/opus-5.5]` | 4 new findings (2 medium, 2 low) and 1 nit, all in code that round 1 changed or the rebase brought in. Round-1 fixes and the issue-34 `self` path confirmed | All **will-fix**, all fixed: #1 the FastAPI path check includes the `root_path` (`1bf112f`) · #2 every live harness stays in the local card registry, and the public URL is claimed (`feae782`) · #3 a second namespace on one embedded database is refused by name (`1b11f73`) · #4 an unsafe `ListTasks` context id is refused with `InvalidParams` (`10fc946`) · nit: dead path-check mode removed (`286bd07`) | [PR #37 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/37#issuecomment-6157706445) |

**Stop condition:** the round cap (`selfReviewCount: 2`) was reached. Round 2 still found
issues, but none repeats a round-1 finding, so `escalateOnRepeatFinding` did not trigger.
The critic round is the next independent check.

## Notes

- Finding #4 and R4: JSON-RPC answers a failed request with HTTP 200 and an error body.
  That is the protocol's form. HTTP+JSON answers 500. Neither carries the resolver's text
  (`test_a_failing_resolver_fails_the_request_without_its_text`).
- Between rounds 1 and 2 the branch was rebased onto `main` (issue-34, #35) at the owner's
  request. The reconciliation (`1d783d3`) is in round 2's scope.
