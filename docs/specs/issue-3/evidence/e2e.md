# End-to-end demo run — T4

`uv run pytest tests/e2e -q -m e2e` on 2026-10-10 at the head of the Layer 9 stack
(`loop/issue-3-l9-demo`), against Temporal Cloud namespace `tiny-harness.gtebu`
(`tiny-harness.gtebu.tmprl.cloud:7233`, API key from the keyring) and OpenAI
`gpt-6.1-sol`. The run started `tiny-harness serve --with-worker` on its own port, task
queue and state directory from a configuration derived from `examples/demo/config.toml`,
drove the task through the A2A SDK client (JSON-RPC, streaming) as participant `alice`,
pressed the A2UI card's button on the first `INPUT_REQUIRED`, answered the second in
text, and read the trace file and the orders ledger afterwards. Every capture below was
redacted by value before it left the test process; the trace attributes were redacted by
the o11y hook at creation.

```text
## uv run pytest tests/e2e -q -m e2e
...                                                                      [100%]
3 passed in 255.95s (0:04:15)
```

## Transcript (`tests/e2e/test_demo.py`)

```text
[   6.6s] task           TASK_STATE_SUBMITTED     9dd85bf0-c7e7-4192-b632-0fb593515c54
[   6.6s] status_update  TASK_STATE_WORKING       
[  47.8s] artifact_update                          a2ui
[  53.2s] status_update  TASK_STATE_INPUT_REQUIRED Please confirm this concerns blender order #48213, not travel cup #48377, and whether the damage was reported within 14 days of its October 6, 2026 delivery (please give the report date). Would you like the $129 refund or a replacement? For a refund, please provide a damage photo; for a replacement, confirm the shipping address (the blender order shows 14 Harbour Lane, Portsea).
[  54.0s] status_update  TASK_STATE_WORKING       
[  57.9s] status_update  TASK_STATE_INPUT_REQUIRED You selected the $129 refund. Before I can issue it, please confirm that this is for blender order #48213, provide a photo of the crack, and give the date the damage was reported so I can verify the 14-day eligibility window after delivery on October 6, 2026.
[  58.7s] status_update  TASK_STATE_WORKING       
[  75.6s] status_update  TASK_STATE_COMPLETED     Your replacement for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking reference NB-48213-R1. No refund was issued, and order #48377 remains unchanged.
```

The flow of requirement 24: plan, `gpt-6.1-sol`, MCP tools, an A2UI card (artifact
`a2ui`, basic catalog), a help request answered over two turns, a terminal state.

## Orders ledger (the MCP server's audit file)

```text
{"tool": "get_order", "arguments": {"order_id": "48213"}, "ts": "2026-10-10T04:42:18.288284+00:00"}
{"tool": "list_open_orders", "arguments": {"order_id": "48213"}, "ts": "2026-10-10T04:42:31.601465+00:00"}
{"tool": "ship_replacement", "arguments": {"order_id": "48213", "address": "14 Harbour Lane, Portsea"}, "ts": "2026-10-10T04:43:08.629014+00:00"}
```

`get_order` and `list_open_orders` are idempotent reads; `ship_replacement`, the
non-idempotent tool, ran exactly once.

## Model calls and prompt caching (R10.3, R18.6)

One `chat gpt-6.1-sol` span per `invoke_llm` activity run (17 of each). From
the second call on, the static prefix (system prompt, participants, skills index, tool
definitions) is served from the provider's cache: `cached_tokens` in the usage response
is non-zero. This assertion depends on the provider serving a cache hit and is the
run's one known source of flakiness; a miss fails the test rather than passing silently.

| Call | input tokens | cached input tokens | output tokens |
|---|---|---|---|
| 1 | 1821 | 0 | 85 |
| 2 | 1977 | 1707 | 19 |
| 3 | 2777 | 1707 | 23 |
| 4 | 3032 | 2774 | 23 |
| 5 | 3230 | 3029 | 154 |
| 6 | 3464 | 1707 | 24 |
| 7 | 3931 | 3461 | 113 |
| 8 | 4154 | 1707 | 83 |
| 9 | 4352 | 1707 | 270 |
| 10 | 4742 | 4349 | 293 |
| 11 | 5073 | 4739 | 109 |
| 12 | 5357 | 5070 | 84 |
| 13 | 5631 | 5354 | 101 |
| 14 | 5865 | 1707 | 33 |
| 15 | 6001 | 5862 | 66 |
| 16 | 6165 | 1707 | 30 |
| 17 | 5865 | 1707 | 45 |

## Tool spans (`execute_tool`, `gen_ai.tool.name`)

| # | Tool |
|---|---|
| 1 | `create_plan` |
| 2 | `load_skill` |
| 3 | `demo-support/orders.get_order` |
| 4 | `demo-support/policy.lookup` |
| 5 | `create_plan` |
| 6 | `demo-support/orders.list_open_orders` |
| 7 | `complete_step` |
| 8 | `complete_step` |
| 9 | `emit_ui` |
| 10 | `emit_ui` |
| 11 | `ask_participant` |
| 12 | `ask_participant` |
| 13 | `complete_step` |
| 14 | `demo-support/orders.ship_replacement` |
| 15 | `complete_step` |
| 16 | `unload_skill` |

## Final task (`GetTask`, with the task extension in `metadata`)

```json
{
  "id": "9dd85bf0-c7e7-4192-b632-0fb593515c54",
  "contextId": "ctx-7411c4e7",
  "status": {
    "state": "TASK_STATE_COMPLETED",
    "message": {
      "messageId": "9dd85bf0-c7e7-4192-b632-0fb593515c54:status:7",
      "contextId": "ctx-7411c4e7",
      "taskId": "9dd85bf0-c7e7-4192-b632-0fb593515c54",
      "role": "ROLE_AGENT",
      "parts": [
        {
          "text": "Your replacement for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking reference NB-48213-R1. No refund was issued, and order #48377 remains unchanged."
        }
      ]
    },
    "timestamp": "2026-10-10T04:43:17.988170Z"
  },
  "metadata": {
    "io.github.madarauchiha-314.tiny-harness/task": {
      "parent_tasks": [],
      "plan": {
        "steps": [
          {
            "linked_tasks": [],
            "id": "verify-the-order",
            "depends_on": [],
            "name": "verify the order",
            "description": "Verify item, price, delivery, warranty, shipping address and open orders.",
            "output": "Order #48213 is a Nimbus 900 blender costing $129, delivered October 6, 2026, with warranty active until October 6, 2027, and shipping address 14 Harbour Lane, Portsea. Open orders also include travel cup #48377 shipping to 3 Quay Street, Portsea; reporter confirmation is required before acting.",
            "state": "done"
          },
          {
            "linked_tasks": [],
            "id": "apply-the-policy",
            "depends_on": [
              "verify-the-order"
            ],
            "name": "apply the policy",
            "description": "Identify damaged-on-arrival eligibility and photo requirements.",
            "output": "Damaged-on-arrival policy offers a refund or replacement within 14 days of delivery. The $129 refund requires a damage photo before issuance; replacement requires no photo. Timing eligibility is not yet confirmed, and reporter must confirm the order and choice before any action; a replacement also requires address confirmation.",
            "state": "done"
          },
          {
            "linked_tasks": [],
            "id": "agree-the-resolution-with-the-customer",
            "depends_on": [
              "apply-the-policy"
            ],
            "name": "agree the resolution with the customer",
            "description": "Present A2UI options and obtain preference, timing confirmation, and any required evidence or address confirmation.",
            "output": "Alice changed the choice from refund to replacement and explicitly authorized shipment for blender order #48213 to its confirmed address, 14 Harbour Lane, Portsea. She confirmed the crack was reported October 6, 2026, on delivery day, meeting the 14-day policy window, and that order #48377 is unrelated. No damage photo is required for replacement.",
            "state": "done"
          },
          {
            "linked_tasks": [],
            "id": "record-the-resolution",
            "depends_on": [
              "agree-the-resolution-with-the-customer"
            ],
            "name": "record the resolution",
            "description": "Execute only the authorized eligible resolution and record the result.",
            "output": "Shipped the authorized replacement for order #48213 to 14 Harbour Lane, Portsea; tracking reference NB-48213-R1. No refund was issued, and unrelated order #48377 was not changed.",
            "state": "done"
          }
        ]
      },
      "goal": "Refund order #48213: the customer says the blender arrived cracked. Check the order and propose a resolution.",
      "sub_tasks": [],
      "name": "Refund order #48213: the customer says the blender arrived c",
      "participants": [
        {
          "id": "alice",
          "kind": "human",
          "display_name": "",
          "role": "reporter"
        },
        {
          "id": "tiny-harness",
          "kind": "agent",
          "display_name": "",
          "role": "assignee"
        }
      ],
      "description": "",
      "acceptance_criteria": [],
      "type": null
    }
  }
}
```

## Trace

[`e2e/trace.json`](e2e/trace.json): the 262 GenAI, MCP and Temporal activity
spans of the run (the polling `events_since` query spans are omitted), one object per
span with `trace_id`, `span_id`, `parent_id`, `start`, `end`, `status` and the redacted
attributes. The JSON-lines exporter wrote them to the run's `trace.jsonl`
(`o11y.trace_file`).
