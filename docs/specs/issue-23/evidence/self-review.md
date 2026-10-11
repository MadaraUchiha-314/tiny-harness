---
type: evidence
phase: needs-review
workItem: issue-23
---

# Self-review: Remove `TINY_HARNESS_PUSH_KEY` from the end-to-end architecture

Two rounds, the operator's cap (`the-loop critic policy`: `selfReviewCount: 2`). Two
findings in round 1, both will-fix and fixed; round 2 found nothing new, so the review
converged.

## Review cycles

| Round | Reviewer | Outcome | Findings → disposition | Link |
|-------|----------|---------|------------------------|------|
| 1 | `claude/claude-opus-5-5` | new findings (2) | (1) `records.py`'s module docstring still named "the push-token cipher" → fixed `7c5d126`; (2) a ticket comment said the design phase was skipped (only `design-approval` was) → correction posted on #23 | [PR #24 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/24#issuecomment-6112631843) |
| 2 | `claude/claude-opus-5-5` | zero (converged) | — | [PR #24 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/24#issuecomment-6112636549) |

## Considered and not raised

- **Hooks and o11y seeing a push record.** The push store writes the plain
  `SqliteStore` directly, as it did before; the `persistence.*` hook points and the o11y
  plugin never receive a `PushConfigRecord`, so plaintext credentials reach no new code.
- **A second writer.** Dropping a legacy row from the `emit_event` sink makes the worker
  delete from the store; the worker already writes to it (the `persist` activity), so the
  SQLite single-writer limit is unchanged.
- **Symlink redirection of the `0600` create.** `O_CREAT | O_EXCL` fails on any existing
  path, a dangling symlink included, so the create cannot be pointed elsewhere; the
  existing-file path is the same `sqlite3.connect` as before.
- **Side effect on a read.** Get and list can now delete a legacy row. That is the
  designed fail-closed behaviour (R4.1, R4.2) and touches only rows no one can use.
