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
inside the `invoke_tool` activity. Killed at **23.1 s**; the activity's
heartbeat stopped, Temporal timed the attempt out after `heartbeat_timeout` (30 s), the
workflow ran `activity.failed` / `activity.retried` through `dispatch_hooks` and
scheduled the attempt again, which the new worker ran.

```text
[  10.6s] task           TASK_STATE_SUBMITTED     41cabe04-4508-4c7a-9bf6-aea547f1de86
[  10.6s] status_update  TASK_STATE_WORKING       
[  86.3s] artifact_update                          a2ui
[  90.4s] status_update  TASK_STATE_INPUT_REQUIRED For order #48213, please confirm whether you want the $129 refund or a replacement, and the date the damage was reported (policy requires reporting within 14 days of October 6, 2026 delivery). For a refund, please provide a photo of the crack; for a replacement, confirm the full shipping address, since your orders use different addresses.
[  91.3s] status_update  TASK_STATE_WORKING       
[ 109.2s] status_update  TASK_STATE_COMPLETED     A replacement blender for order #48213 has been arranged to 14 Harbour Lane, Portsea, with tracking **NB-48213-R1**. No refund was issued, and order #48377 was left unchanged.
```

Activity attempts from the workflow history (`fetch_history_events`):

| Activity | scheduled | completed | timed out | failed |
|---|---|---|---|---|
| `assemble_context` | 16 | 16 | 0 | 0 |
| `compaction_trigger` | 16 | 16 | 0 | 0 |
| `decide_completion` | 1 | 1 | 0 | 0 |
| `dispatch_hooks` | 1 | 1 | 0 | 0 |
| `emit_event` | 5 | 5 | 0 | 0 |
| `intake` | 2 | 2 | 0 | 0 |
| `invoke_llm` | 16 | 16 | 0 | 0 |
| `invoke_tool` | 16 | 15 | 1 | 0 |
| `persist` | 17 | 17 | 0 | 0 |
| `send_channel_message` | 1 | 1 | 0 | 0 |

Ledger for this task: `get_order, get_order, list_open_orders, ship_replacement` — `get_order` ran twice (the
timed-out attempt and its retry; it is declared idempotent), `ship_replacement` once.

Worker 1, last operations before the kill:

```text
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "41cabe04-4508-4
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "41cabe04-4508-4
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "41cabe04-4508
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "41cabe04-4508-4c7
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "41cabe04-4508-4
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "41cabe04-4508-4
```

Worker 2, first operations after restart (the retried `tool.invoked`):

```text
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "error.message": "activity Heartbeat timeout", "error.type": "TimeoutError", "level": "WARNING", "logger": "tiny_harness
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "error.message": "activity Heartbeat timeout", "error.type": "TimeoutError", "level": "INFO", "logger": "tiny_harness.o1
{"activity": "invoke_tool", "attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "activity.retried.pre", "next_delay_seconds": 0.837192, "operatio
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "41cabe04-4508-4
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "41cabe04-4508
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "41cabe04-4508-4c7
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "41cabe04-4508-4
{"attempt": 1, "correlation_id": "41cabe04-4508-4c7a-9bf6-aea547f1de86", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "41cabe04-4508-4
```

## Kill 2: while the task waits in `INPUT_REQUIRED`

Killed at **151.9 s**, right after the help request arrived and
before the reply was sent; the reply went to the restarted worker.

```text
[ 110.3s] task           TASK_STATE_SUBMITTED     6a3e14c6-993f-4afb-9afb-378407604215
[ 110.3s] status_update  TASK_STATE_WORKING       
[ 147.5s] artifact_update                          a2ui
[ 151.9s] status_update  TASK_STATE_INPUT_REQUIRED Order #48213 is the $129 Nimbus 900 blender, delivered October 6, 2026. Please confirm the damage was reported within 14 days of delivery and choose a $129 refund or replacement. For a refund, please provide the required damage photo; for a replacement, confirm the shipping address (this customer has orders at two different addresses). No refund or shipment has been made.
[ 163.4s] status_update  TASK_STATE_WORKING       
[ 180.7s] status_update  TASK_STATE_COMPLETED     Your replacement Nimbus 900 blender for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking **NB-48213-R1**. No refund was issued, and order #48377 was left unchanged.
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
{"attempt": 1, "correlation_id": "6a3e14c6-993f-4afb-9afb-378407604215", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "6a3e14c6-993f-4af
{"attempt": 1, "correlation_id": "6a3e14c6-993f-4afb-9afb-378407604215", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "6a3e14c6-993f-4
{"attempt": 1, "correlation_id": "6a3e14c6-993f-4afb-9afb-378407604215", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.pre", "operation": "tool.invoked", "phase": "pre", "task_id": "6a3e14c6-993f-4
{"attempt": 1, "correlation_id": "6a3e14c6-993f-4afb-9afb-378407604215", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "tool.invoked.post", "operation": "tool.invoked", "phase": "post", "task_id": "6a3e14c6-993f
{"attempt": 1, "correlation_id": "6a3e14c6-993f-4afb-9afb-378407604215", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.pre", "operation": "llm.invoked", "phase": "pre", "task_id": "6a3e14c6-993f-4af
{"attempt": 1, "correlation_id": "6a3e14c6-993f-4afb-9afb-378407604215", "level": "INFO", "logger": "tiny_harness.o11y", "msg": "llm.invoked.post", "operation": "llm.invoked", "phase": "post", "task_id": "6a3e14c6-993f-4
```

## Trace

The o11y spans of the run are in the test's `trace.jsonl` (one file shared by the
server and the three workers); the spans of the attempt killed mid-flight were never
exported, which is why the attempt table above comes from Temporal's history rather
than from span counts. `e2e/trace.json` holds the demo run's spans.
