# Capability: persistence

> A store entity holds the read model that outlives the workflow; Temporal history is the
> replay source; no secret is stored, with one exception the store protects at rest.

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
  writer, no replication. It creates its parent directory, and a new database file with
  mode `0600` (an existing file keeps its mode).
- WHEN a write fails THEN a `StoreWriteError` SHALL reach the calling operation and the
  operation SHALL NOT be reported complete.
- No record field SHALL be a credential. The one exception is a push config's
  client-supplied callback `token` and `authentication`, kept as supplied in `SecretStr`
  fields (masked wherever a record is printed, revealed only when the store serialises
  it). tiny-harness applies no encryption of its own: protecting them at rest is the
  `Store` implementation's job, or the volume's under the default SQLite store.
- WHEN a push config stored encrypted by version 0.5 or earlier is read THEN it SHALL be
  deleted, logged at `WARNING` by task and config id, and neither returned nor
  delivered to.
- Every record kind SHALL have a time to live (`[retention]`, 30 days by default; tasks
  and plans measured from the terminal state), applied by the heartbeat's retention
  sweep; `tiny-harness tasks purge <task-id>` terminates one task's workflow, then
  deletes its rows (and media), so the workflow writes nothing after the delete.
- Persistence reads and writes SHALL run through the `persistence.read` and
  `persistence.write` hook points, so a hook can replace the target.
- The media store (see [media](media.md)) SHALL keep each task's images and audio as
  files beside the SQLite store; the retention sweep SHALL delete the media of each task
  whose record it deletes and every object older than `[retention] media` (default 30
  days), and `tiny-harness tasks purge` SHALL delete the task's media too.

## Design

[design.md § Persistence](../specs/issue-3/design.md#persistence-r11--harnesspersistence),
[design.md § Security design](../specs/issue-3/design.md#security-design) (data retention);
[issue-23 design](../specs/issue-23/design.md) (push-config credentials at rest).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Records, the store entity, SQLite store, push-token cipher (Layer 4); retention sweep and purge (Layer 5) | [spec](../specs/issue-3/), [PR #10](https://github.com/MadaraUchiha-314/tiny-harness/pull/10), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11) |
| issue-23 | Push-token cipher removed: push-config credentials kept as supplied in `SecretStr` fields, protected at rest by the store; 0.5.x encrypted rows dropped; new SQLite file `0600` | [spec](../specs/issue-23/), [PR #24](https://github.com/MadaraUchiha-314/tiny-harness/pull/24) |
| issue-38 | The media store's retention (`[retention] media`) and purge | [spec](../specs/issue-38/), [PR #39](https://github.com/MadaraUchiha-314/tiny-harness/pull/39), [decision-010](../decisions/decision-010.md) |
