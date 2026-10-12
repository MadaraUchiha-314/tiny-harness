---
type: evidence
workItem: issue-25
---

# Design critic review: Make the CLI/TUI experience seamless

> Written only when the work item selected the opt-in `design-critic-review` phase
> (issue-188). A different model or harness reads the completed `design.md` against the
> requirements, before the testing plan and the task DAG are derived from it. The node
> blocks until this section is filled in.

## Design critic review

| Round | Critic (`<harness>/<model>`) | Outcome | Findings → disposition | Link |
|-------|-----------------------------|---------|------------------------|------|
| 1 | `[codex/gpt-6.1-sol]` | 8 findings (4 high, 4 medium). All 8 are will-fix, applied with one commit each | see table below | [PR #26 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/26#issuecomment-6114247608) |

- **Runtime.** Round 1 ran in 75.8 s. Usage: input 69,251, output 2,798 and cache read
  348,160 tokens.
- **How it ran.** It ran in-process (`THE_LOOP_SERVICE_LOCAL=1`, 900 s timeout) to avoid
  the control-plane service's fixed 120 s client timeout.
- **Scope.** The prompt named `requirements.md`, `design.md` and the prototypes, and
  allowed reading `tiny_harness/` and `renderers/web/src/` to check the design's claims
  about existing code.

### Findings and dispositions

| # | Finding | Severity | Disposition → commit |
|---|---------|----------|----------------------|
| 1 | New-task envelopes bypass the model allowlist (`executor.py:73`) | high | will-fix → cdcac27 |
| 2 | A refused completion can already interrupt the task (`workflows.py:341`, `:500`) | high | will-fix → b083edc |
| 3 | Plugin command bodies remain registered without name filtering (`loader.py:315`) | high | will-fix → 36ba123 |
| 4 | Command-only messages have no defined path around the core loop (`workflows.py:414`, `loop.py:190`) | high | will-fix → bd11246 |
| 5 | Leaving participant workflows unchanged makes commands complete them (`workflows.py:536`) | medium | will-fix → 48bc8a9 |
| 6 | Compaction and help ignore the task's chosen settings | medium | will-fix → 403a10d |
| 7 | Agent-spawned children do not inherit model settings (`workflows.py:798`) | medium | will-fix → 8711924 |
| 8 | The `/sub-task` handler cannot reply with the generated id (`workflows.py:768`) | medium | will-fix → fb97264 |

**Convergence.**

- The operator's policy is one critic round (`criticReviewCount: 1`, from
  `the-loop critic policy`).
- Every finding is dispositioned, and none is won't-fix.
- No finding needs a human decision.
- The design goes to `design-approval` with all eight resolved.
