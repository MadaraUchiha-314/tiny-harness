# Capability: heartbeat

> A Temporal schedule wakes the harness every interval to poll the channels, snapshot the
> running tasks and sweep expired records.

## What it is

The periodic pulse that makes waiting tasks progress without an inbound request and keeps
the store within its retention policy. A schedule, not a process loop, so it survives the
server process and is visible in Temporal. Lives in `tiny_harness/service/heartbeat.py`.

## Current behaviour

- The worker SHALL ensure the schedule `tiny-harness-heartbeat` exists, starting
  `HeartbeatWorkflow` every `[heartbeat] interval` (30 s by default) on the configured
  task queue; `tiny-harness schedules delete` removes it.
- Each tick SHALL run `poll_channels` (forwarding pending channel items to their tasks),
  `monitor_snapshot` (the task states and pending items) and `retention_sweep` (deleting
  expired store rows per kind).
- WHEN a tick finds a task waiting on input whose reply has arrived THEN the task SHALL
  be resumed.
- The snapshot SHALL be exposed to the API layer at `GET /_monitor` and to hooks through
  the `heartbeat.tick` operation.
- WHEN a tick fails THEN the failure SHALL be logged and the next tick run on schedule.

## Design

[design.md § Heartbeat](../specs/issue-3/design.md#heartbeat-r16--serviceheartbeatpy).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | The heartbeat workflow, schedule and activities (Layer 5) | [spec](../specs/issue-3/), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11) |
