---
type: evidence
phase: needs-review
workItem: issue-17
---

# Self-review: issue-17

Work item: issue-17 · node `self-review` · reviewer `claude/opus-5.5` (the running
harness) · policy from `the-loop critic policy`: `selfReviewCount: 2`,
`stopOnNoNewFindings: true`, `escalateOnRepeatFinding: true`.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition → commit | Link |
|---|---|---|---|---|
| 1 | `claude/opus-5.5` | 3 new findings | (1) security/medium: download dir or cached binary another user could swap → will-fix → `0471c9b`; (2) correctness/medium: dev server left running when a step after its start fails → will-fix → `44d8154`; (3) validation/low: unbounded `temporal.embedded.port` → will-fix → `22c13bc` | [findings](https://github.com/MadaraUchiha-314/tiny-harness/pull/18#issuecomment-6100302614), [replies](https://github.com/MadaraUchiha-314/tiny-harness/pull/18#issuecomment-6100302825) |
| 2 | `claude/opus-5.5` | 3 new findings, none repeated | (1) correctness/medium: `api_key` not refused in embedded mode for `Settings` built in code → will-fix → `777bf60`; (2) hardening/low: TUI-hosted log not owner-only → will-fix → `83799a0`; (3) docs/low: download-dir rule out of date → will-fix → `12f218f`. Checked, not a finding: `serve` with the A2A port taken exits cleanly and stops the embedded server | [findings and replies](https://github.com/MadaraUchiha-314/tiny-harness/pull/18#issuecomment-6100337189) |

The cap of 2 rounds was reached; no finding recurred, so no escalation was triggered.
Every fix landed as its own commit with a test that went red first.

## Found earlier, during implementation and verification

Not review rounds, but the same kind of evidence, and each fixed red→green:

- The dev server does not create its schema in a pre-existing empty file, so design.md's
  "pre-create the database `0600`" could not work as written. The file is tightened
  before and after start instead (`3410409`).
- A plain SIGTERM handler raising `KeyboardInterrupt` hung `serve` with the dev server
  running. SIGTERM now cancels the main task (`cf2308c`).
- In the TUI-hosted mode, uvicorn's access log and the dev server's banner drew on the
  TUI's terminal. Found by the T11 walkthrough (`116199d`).
- The dev server opens about five loopback ports, not the one design.md assumed. All of
  them are verified to be on 127.0.0.1 (`cf2308c`).
