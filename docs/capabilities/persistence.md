# Capability: persistence

> A store entity holds the read model that outlives the workflow; Temporal history is the
> replay source; no secret is stored, with one encrypted exception.

## What it is

What survives beyond a workflow's history: task records, plans, state summaries, channel
messages, inbox audit rows, compaction records and push-notification configs. The
default store is SQLite; a plugin implements `Store` for a production database. Lives in
`tiny_harness/harness/persistence/`.

## Current behaviour

- The store SHALL persist task records on every state change, plans when attached or
  changed, the state summary per turn, channel messages before delivery, inbox audit
  rows, compaction records and push-notification configs. Temporal's history persists
  every activity input and result; nothing is stored twice without a reason.
- The default store SHALL be `SqliteStore` on the standard library's `sqlite3`: one table
  per record kind with the record's JSON and indexed id, context, task and timestamp
  columns, every call run in a thread under one lock. Its limits: a single-process
  writer, no replication. It creates its parent directory.
- WHEN a write fails THEN a `StoreWriteError` SHALL reach the calling operation and the
  operation SHALL NOT be reported complete.
- No record field SHALL be a credential. The one exception is a push config's
  client-supplied callback token, stored AES-GCM encrypted under
  `TINY_HARNESS_PUSH_KEY` and decrypted only inside the `emit_event` activity.
- Every record kind SHALL have a time to live (`[retention]`, 30 days by default; tasks
  and plans measured from the terminal state), applied by the heartbeat's retention
  sweep; `tiny-harness tasks purge <task-id>` deletes one task's rows and terminates its
  workflow.
- Persistence reads and writes SHALL run through the `persistence.read` and
  `persistence.write` hook points, so a hook can replace the target.

## Design

[design.md § Persistence](../specs/issue-3/design.md#persistence-r11--harnesspersistence),
[design.md § Security design](../specs/issue-3/design.md#security-design) (data retention).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Records, the store entity, SQLite store, push-token cipher (Layer 4); retention sweep and purge (Layer 5) | [spec](../specs/issue-3/), [PR #10](https://github.com/MadaraUchiha-314/tiny-harness/pull/10), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11) |
