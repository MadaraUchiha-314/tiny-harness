# Capability: durable-execution

> One Temporal workflow per task runs the core loop; every model call, tool call,
> persistence write and channel send is an activity; retries are workflow-managed with
> hooks between attempts; Temporal covers the whole request lifecycle.

## What it is

Why a pod restart never loses or duplicates work. The workflow never calls a model or a
tool; it schedules activities whose typed results are recorded in history, so a replay
reuses them. Lives in `tiny_harness/service/durable/`.

## Current behaviour

- `TaskWorkflow` SHALL run the core loop over an activity-backed port: `intake`,
  `assemble_context`, `compaction_trigger`, `compact`, `invoke_llm`, `invoke_tool`,
  `decide_completion`, `persist`, `emit_event`, `send_channel_message`,
  `dispatch_hooks`; `RemoteTaskWorkflow` runs `run_remote_agent_turn` and
  `HeartbeatWorkflow` runs `poll_channels`, `monitor_snapshot` and `retention_sweep`.
  These are the names `[retries] per_activity` overrides. The workflow id is the task id.
- WHEN a workflow is replayed THEN no activity whose result is in history SHALL run
  again: a worker crash mid-task is followed by the task completing on another worker
  with every `invoke_llm` scheduled once and completed once.
- Each activity SHALL be scheduled with `maximum_attempts=1`; on failure the workflow
  SHALL run `activity.failed.pre` and `activity.retried.pre` through `dispatch_hooks`,
  wait a jittered exponential backoff (`workflow.random()`), and schedule the next
  attempt under the configured policy (`[retries]`, overridable per activity). A tool
  that is not declared idempotent SHALL NOT be retried; its step fails with a typed
  error a hook can override.
- LLM and tool activities SHALL heartbeat every 10 s; a dead worker is detected within
  `heartbeat_timeout` (30 s) or the start-to-close timeout and the attempt rescheduled.
- The `inbox` update SHALL append a message to the workflow's mailbox (handlers run
  before `run`, so a message that arrives with the start is merged, not overwritten);
  the loop drains the mailbox at the top of each turn; an idle task waits in
  `wait_condition` and consumes no worker. `cancel` and `child_done` are signals;
  `task`, `events_since` and `monitor` are queries.
- The workflow SHALL keep a durable event log (`seq`, `kind`, `payload`) that the A2A
  server streams and replays, and SHALL persist the final state before returning.
- WHEN the history passes `history_event_bound` or Temporal suggests it THEN the
  workflow SHALL continue as new carrying the whole `TaskStart` (task, state, mailbox,
  seen message ids, event log, pending help request). The first turn of a run never
  continues as new.
- Sub-tasks SHALL run as child workflows with `ParentClosePolicy.ABANDON` and signal
  `child_done`; remote delegations as `RemoteTaskWorkflow` driving the A2A client.
- Workflow code SHALL run in Temporal's sandbox; the passthrough list is
  `tiny_harness`, `pydantic`, `pydantic_core`, `a2a`, `google.protobuf`, `jsonschema`,
  `packaging`, `httpx`, `starlette`, `anyio`, `sniffio`, `mcp`, `cryptography`, `yaml`
  and `opentelemetry` (pure models and SDK types, none called for I/O in the workflow);
  `build_replayer()` uses the same runner.
- Payloads SHALL be typed Pydantic models carried by Temporal's Pydantic data converter,
  A2A protos as ProtoJSON fields, every activity input carrying its attempt number.
- The client SHALL connect to Temporal Cloud with TLS and `TEMPORAL_API_KEY`; the e2e
  namespace is `tiny-harness.gtebu` at `tiny-harness.gtebu.tmprl.cloud:7233`. The
  search attributes `A2AContextId`, `A2ATaskState` and `TinyHarnessAgent` SHALL be used
  only when `search_attributes = true`, because an unregistered attribute fails the
  workflow's first task.
- Inbox intake, heartbeat ticks and channel delivery SHALL be workflow or activity code;
  the A2A executor starts or signals a workflow and returns.
- Every process SHALL reach Temporal through `temporal_client(settings)`
  (`durable/temporal.py`): `connect()` in remote mode, or, in embedded mode, an
  `EmbeddedTemporal` that starts the Temporal CLI dev server
  (`WorkflowEnvironment.start_local`) with the same Pydantic converter and tracing
  interceptor, bound to `127.0.0.1` (every port it opens, frontend, metrics and internal
  services alike), with the Web UI off, and stops it on every exit path.
- WHILE embedded state is persisted, the SQLite file and its `-wal`/`-shm` SHALL be
  `0600` (tightened before start when the file exists and right after start when the
  server created it), and an exclusive `flock` on `<database>.lock` SHALL refuse a second
  owner. A restart on the same file resumes the running workflows.
- The dev server binary SHALL come from `temporal.embedded.binary_path` (no download) or
  be downloaded once into a `0700` user cache directory, never the system temp directory;
  a download directory, or a cached binary in it, that another user owns or can write is
  refused. A failed start raises
  `EmbeddedTemporalError` and never falls back to a remote Temporal.

## Design

[design.md § Durable execution](../specs/issue-3/design.md#durable-execution-r19--servicedurable),
[design.md § A request's life](../specs/issue-3/design.md#a-requests-life),
[decision-002](../decisions/decision-002.md),
[issue-17 design.md](../specs/issue-17/design.md), [decision-005](../decisions/decision-005.md).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Workflows, activities, client, worker, child and remote workflows, heartbeat (Layer 5); `emit_ui` and surfaces in the workflow (Layer 7); opt-in search attributes (Layer 9) | [spec](../specs/issue-3/), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11), [decision-002](../decisions/decision-002.md) |
| issue-17 | `temporal_client` and embedded Temporal mode: the dev server as an owned child process, loopback-only, persisted `0600` under a state lock | [spec](../specs/issue-17/), [PR #18](https://github.com/MadaraUchiha-314/tiny-harness/pull/18), [decision-005](../decisions/decision-005.md) |
