# Crash recovery — T12

`uv run pytest tests/e2e -q -m e2e -k crash_recovery` on 2026-10-10 (the same run as
`e2e.md`, which ran all three tests at the final head). The server (`tiny-harness serve`) and the worker (`tiny-harness worker`) ran
as separate processes on Temporal Cloud; the test killed the worker with `SIGKILL` and
started a new one. The proof is Temporal's history: for the task's workflow, every
`invoke_llm` activity was scheduled once and completed once (no duplicated LLM call,
R19.2, R24.5), and the orders ledger shows the non-idempotent `ship_replacement` once.
Timestamps are seconds since the test's start; logs are redacted.

## Kill 1: during an idempotent tool activity (`get_order`)

The orders server held `get_order` open (the `slow-get-order` marker) so the kill landed
inside the `invoke_tool` activity. Killed at **24.6 s**; the activity's
heartbeat stopped, Temporal timed the attempt out after `heartbeat_timeout` (30 s), the
workflow ran `activity.failed` / `activity.retried` through `dispatch_hooks` and
scheduled the attempt again, which the new worker ran.

```text
[  12.3s] task           TASK_STATE_SUBMITTED     861c8b61-f51e-4625-afaa-879a09b33288
[  12.3s] status_update  TASK_STATE_WORKING       
[  80.1s] artifact_update                          a2ui
[  84.5s] status_update  TASK_STATE_INPUT_REQUIRED Please confirm this concerns blender order #48213 (not travel-cup order #48377) and that the complaint was made within 14 days of its October 6 delivery. Do you want the full $129 refund or a replacement? For a refund, please supply a photo of the crack first; for a replacement, please confirm the shipping address (the blender's address is 14 Harbour Lane, Portsea).
[  85.0s] status_update  TASK_STATE_WORKING       
[  99.9s] status_update  TASK_STATE_COMPLETED     Your replacement blender for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking **NB-48213-R1**. No refund was issued, and order #48377 was left unchanged.
```

Activity attempts from the workflow history (`fetch_history_events`):

| Activity | scheduled | completed | timed out | failed |
|---|---|---|---|---|
| `assemble_context` | 14 | 14 | 0 | 0 |
| `compaction_trigger` | 14 | 14 | 0 | 0 |
| `decide_completion` | 1 | 1 | 0 | 0 |
| `dispatch_hooks` | 1 | 1 | 0 | 0 |
| `emit_event` | 5 | 5 | 0 | 0 |
| `intake` | 2 | 2 | 0 | 0 |
| `invoke_llm` | 14 | 14 | 0 | 0 |
| `invoke_tool` | 14 | 13 | 1 | 0 |
| `persist` | 15 | 15 | 0 | 0 |
| `send_channel_message` | 1 | 1 | 0 | 0 |

Ledger for this task: `get_order, get_order, list_open_orders, ship_replacement` — `get_order` ran twice (the
timed-out attempt and its retry; it is declared idempotent), `ship_replacement` once.

Worker 1, last operations before the kill:

```text
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "861c8b61-f51e-4
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "861c8b61-f51e-4
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "861c8b61-f51e
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "861c8b61-f51e-462
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "861c8b61-f51e-4
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "861c8b61-f51e-4
```

Worker 2, first operations after restart (the retried `tool.invoked`):

```text
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "error.message": "activity Heartbeat timeout", "error.type": "TimeoutError", "level": "WARNING", "logger": "tiny_harness
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "error.message": "activity Heartbeat timeout", "error.type": "TimeoutError", "level": "INFO", "logger": "tiny_harness.o1
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "activity.retried.pre", "next_delay_seconds": 0.98493, "operation
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "861c8b61-f51e-4
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "861c8b61-f51e
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "861c8b61-f51e-462
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "861c8b61-f51e-4
{"attempt": 1, "correlation_id": "861c8b61-f51e-4625-afaa-879a09b33288", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "861c8b61-f51e-4
```

## Kill 2: while the task waits in `INPUT_REQUIRED`

Killed at **142.8 s**, right after the help request arrived and
before the reply was sent; the reply went to the restarted worker.

```text
[ 101.0s] task           TASK_STATE_SUBMITTED     f8e0cb05-eb7b-4595-8aa7-c5014a9bda70
[ 101.0s] status_update  TASK_STATE_WORKING       
[ 138.5s] artifact_update                          a2ui
[ 142.8s] status_update  TASK_STATE_INPUT_REQUIRED Please confirm this concerns the Nimbus 900 blender in order #48213 (not travel cup order #48377), and tell me when the damage was reported so I can verify the 14-day window after October 6, 2026 delivery. Would you like the $129 refund or a replacement? For a refund, please provide a photo of the crack; for replacement, please confirm the shipping address (the blender order lists 14 Harbour Lane, Portsea).
[ 153.8s] status_update  TASK_STATE_WORKING       
[ 170.0s] status_update  TASK_STATE_COMPLETED     Your replacement for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking number **NB-48213-R1**. No refund was issued, and order #48377 was left unchanged.
```

| Activity | scheduled | completed | timed out | failed |
|---|---|---|---|---|
| `assemble_context` | 14 | 14 | 0 | 0 |
| `compaction_trigger` | 14 | 14 | 0 | 0 |
| `decide_completion` | 1 | 1 | 0 | 0 |
| `emit_event` | 5 | 5 | 0 | 0 |
| `intake` | 2 | 2 | 0 | 0 |
| `invoke_llm` | 14 | 14 | 0 | 0 |
| `invoke_tool` | 13 | 13 | 0 | 0 |
| `persist` | 15 | 15 | 0 | 0 |
| `send_channel_message` | 1 | 1 | 0 | 0 |

Ledger for this task: `get_order, list_open_orders, ship_replacement`. No activity was in flight at the
kill, so every activity has exactly one attempt; the waiting workflow consumed no worker
and resumed on the reply (R12.6, R19.7).

Worker 3, first operations after restart (the reply's turn):

```text
{"attempt": 1, "correlation_id": "f8e0cb05-eb7b-4595-8aa7-c5014a9bda70", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "f8e0cb05-eb7b-459
{"attempt": 1, "correlation_id": "f8e0cb05-eb7b-4595-8aa7-c5014a9bda70", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "f8e0cb05-eb7b-4
{"attempt": 1, "correlation_id": "f8e0cb05-eb7b-4595-8aa7-c5014a9bda70", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "f8e0cb05-eb7b-4
{"attempt": 1, "correlation_id": "f8e0cb05-eb7b-4595-8aa7-c5014a9bda70", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "f8e0cb05-eb7b
{"attempt": 1, "correlation_id": "f8e0cb05-eb7b-4595-8aa7-c5014a9bda70", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "f8e0cb05-eb7b-459
{"attempt": 1, "correlation_id": "f8e0cb05-eb7b-4595-8aa7-c5014a9bda70", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "f8e0cb05-eb7b-4
```

## Trace

The o11y spans of the run are in the test's `trace.jsonl` (one file shared by the
server and the three workers); the spans of the attempt killed mid-flight were never
exported, which is why the attempt table above comes from Temporal's history rather
than from span counts. `e2e/trace.json` holds the demo run's spans.
