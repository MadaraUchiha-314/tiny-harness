# Crash recovery — T12

`uv run pytest tests/e2e -q -m e2e -k crash_recovery` on 2026-10-10 (the same run as
`e2e.md`). The server (`tiny-harness serve`) and the worker (`tiny-harness worker`) ran
as separate processes on Temporal Cloud; the test killed the worker with `SIGKILL` and
started a new one. The proof is Temporal's history: for the task's workflow, every
`invoke_llm` activity was scheduled once and completed once (no duplicated LLM call,
R19.2, R24.5), and the orders ledger shows the non-idempotent `ship_replacement` once.
Timestamps are seconds since the test's start; logs are redacted.

## Kill 1: during an idempotent tool activity (`get_order`)

The orders server held `get_order` open (the `slow-get-order` marker) so the kill landed
inside the `invoke_tool` activity. Killed at **22.6 s**; the activity's
heartbeat stopped, Temporal timed the attempt out after `heartbeat_timeout` (30 s), the
workflow ran `activity.failed` / `activity.retried` through `dispatch_hooks` and
scheduled the attempt again, which the new worker ran.

```text
[  11.2s] task           TASK_STATE_SUBMITTED     ecf5c4e7-8f9d-4e27-9863-c2083c095dcd
[  11.2s] status_update  TASK_STATE_WORKING       
[  85.6s] artifact_update                          a2ui
[  90.1s] status_update  TASK_STATE_INPUT_REQUIRED I'm sorry the blender arrived cracked. Would you like a $129 refund or a replacement for order #48213, and on what date was the damage reported (the policy covers reports within 14 days of the October 6 delivery)? For a refund, please provide a photo of the damage. If you choose replacement, please confirm the shipping address: your orders show both 14 Harbour Lane and 3 Quay Street, Portsea.
[  91.0s] status_update  TASK_STATE_WORKING       
[ 105.1s] status_update  TASK_STATE_COMPLETED     Your replacement for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking number **NB-48213-R1**. No refund was issued, and order #48377 remains unchanged.
```

Activity attempts from the workflow history (`fetch_history_events`):

| Activity | scheduled | completed | timed out | failed |
|---|---|---|---|---|
| `assemble_context` | 15 | 15 | 0 | 0 |
| `compaction_trigger` | 15 | 15 | 0 | 0 |
| `decide_completion` | 1 | 1 | 0 | 0 |
| `dispatch_hooks` | 1 | 1 | 0 | 0 |
| `emit_event` | 5 | 5 | 0 | 0 |
| `intake` | 2 | 2 | 0 | 0 |
| `invoke_llm` | 15 | 15 | 0 | 0 |
| `invoke_tool` | 15 | 14 | 1 | 0 |
| `persist` | 16 | 16 | 0 | 0 |
| `send_channel_message` | 1 | 1 | 0 | 0 |

Ledger for this task: `get_order, get_order, list_open_orders, ship_replacement` — `get_order` ran twice (the
timed-out attempt and its retry; it is declared idempotent), `ship_replacement` once.

Worker 1, last operations before the kill:

```text
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "ecf5c4e7-8f9d-4
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "ecf5c4e7-8f9d-4
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "ecf5c4e7-8f9d
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "ecf5c4e7-8f9d-4e2
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "ecf5c4e7-8f9d-4
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "ecf5c4e7-8f9d-4
```

Worker 2, first operations after restart (the retried `tool.invoked`):

```text
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "error.message": "activity Heartbeat timeout", "error.type": "TimeoutError", "level": "WARNING", "logger": "tiny_harness
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "error.message": "activity Heartbeat timeout", "error.type": "TimeoutError", "level": "INFO", "logger": "tiny_harness.o1
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "activity.retried.pre", "next_delay_seconds": 1.042408, "operatio
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "ecf5c4e7-8f9d-4
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "ecf5c4e7-8f9d
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "ecf5c4e7-8f9d-4e2
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "ecf5c4e7-8f9d-4
{"attempt": 1, "correlation_id": "ecf5c4e7-8f9d-4e27-9863-c2083c095dcd", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "ecf5c4e7-8f9d-4
```

## Kill 2: while the task waits in `INPUT_REQUIRED`

Killed at **146.9 s**, right after the help request arrived and
before the reply was sent; the reply went to the restarted worker.

```text
[ 106.7s] task           TASK_STATE_SUBMITTED     32fbc95e-c3d7-4d54-8ccf-5991eb9a3c71
[ 106.7s] status_update  TASK_STATE_WORKING       
[ 143.0s] artifact_update                          a2ui
[ 146.9s] status_update  TASK_STATE_INPUT_REQUIRED Please confirm this concerns blender order #48213, not travel-cup order #48377, and whether the damage was reported within 14 days of its October 6, 2026 delivery (please provide the report date). Would you like the $129 refund or a replacement? For a refund, please provide a photo of the damage first; for a replacement, please confirm the shipping address, since the orders have different addresses.
[ 158.6s] status_update  TASK_STATE_WORKING       
[ 175.7s] status_update  TASK_STATE_COMPLETED     Your replacement for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking number **NB-48213-R1**. No refund was issued, and order #48377 was left unchanged.
```

| Activity | scheduled | completed | timed out | failed |
|---|---|---|---|---|
| `assemble_context` | 15 | 15 | 0 | 0 |
| `compaction_trigger` | 15 | 15 | 0 | 0 |
| `decide_completion` | 1 | 1 | 0 | 0 |
| `emit_event` | 5 | 5 | 0 | 0 |
| `intake` | 2 | 2 | 0 | 0 |
| `invoke_llm` | 15 | 15 | 0 | 0 |
| `invoke_tool` | 14 | 14 | 0 | 0 |
| `persist` | 16 | 16 | 0 | 0 |
| `send_channel_message` | 1 | 1 | 0 | 0 |

Ledger for this task: `get_order, list_open_orders, ship_replacement`. No activity was in flight at the
kill, so every activity has exactly one attempt; the waiting workflow consumed no worker
and resumed on the reply (R12.6, R19.7).

Worker 3, first operations after restart (the reply's turn):

```text
{"attempt": 1, "correlation_id": "32fbc95e-c3d7-4d54-8ccf-5991eb9a3c71", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "32fbc95e-c3d7-4d5
{"attempt": 1, "correlation_id": "32fbc95e-c3d7-4d54-8ccf-5991eb9a3c71", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "32fbc95e-c3d7-4
{"attempt": 1, "correlation_id": "32fbc95e-c3d7-4d54-8ccf-5991eb9a3c71", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "32fbc95e-c3d7-4
{"attempt": 1, "correlation_id": "32fbc95e-c3d7-4d54-8ccf-5991eb9a3c71", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "32fbc95e-c3d7
{"attempt": 1, "correlation_id": "32fbc95e-c3d7-4d54-8ccf-5991eb9a3c71", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "32fbc95e-c3d7-4d5
{"attempt": 1, "correlation_id": "32fbc95e-c3d7-4d54-8ccf-5991eb9a3c71", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "32fbc95e-c3d7-4
```

## Trace

The o11y spans of the run are in the test's `trace.jsonl` (one file shared by the
server and the three workers); the spans of the attempt killed mid-flight were never
exported, which is why the attempt table above comes from Temporal's history rather
than from span counts. `e2e/trace.json` holds the demo run's spans.
