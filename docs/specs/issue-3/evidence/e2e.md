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
3 passed in 242.73s (0:04:02)
```

## Transcript (`tests/e2e/test_demo.py`)

```text
[   5.5s] task           TASK_STATE_SUBMITTED     96086ae3-a399-4ba3-9c00-c2057b0ecbbc
[   5.5s] status_update  TASK_STATE_WORKING       
[  43.8s] artifact_update                          a2ui
[  48.1s] status_update  TASK_STATE_INPUT_REQUIRED For order #48213, please confirm whether you choose the $129 refund or a replacement, and when the cracked blender was first reported (the policy requires reporting within 14 days of October 6, 2026). For a refund, please provide a photo of the damage before I issue it. If choosing a replacement, please confirm the shipping address: this blender order lists 14 Harbour Lane, Portsea, while your other open order lists 3 Quay Street, Portsea. Nothing has been refunded or shipped.
[  48.6s] status_update  TASK_STATE_WORKING       
[  52.2s] status_update  TASK_STATE_INPUT_REQUIRED You've selected the $129 refund for order #48213. Before I can issue it, please provide a photo of the cracked blender and the date the damage was first reported, so I can confirm it was within 14 days of delivery on October 6, 2026.
[  53.0s] status_update  TASK_STATE_WORKING       
[  69.2s] status_update  TASK_STATE_COMPLETED     Your replacement blender for order #48213 is shipping to 14 Harbour Lane, Portsea; tracking number: **NB-48213-R1**. No refund was issued, and order #48377 was left unchanged.
```

The flow of requirement 24: plan, `gpt-6.1-sol`, MCP tools, an A2UI card (artifact
`a2ui`, basic catalog), a help request answered over two turns, a terminal state.

## Orders ledger (the MCP server's audit file)

```text
{"tool": "get_order", "arguments": {"order_id": "48213"}, "ts": "2026-10-10T08:46:46.624251+00:00"}
{"tool": "list_open_orders", "arguments": {"order_id": "48213"}, "ts": "2026-10-10T08:46:59.534411+00:00"}
{"tool": "ship_replacement", "arguments": {"order_id": "48213", "address": "14 Harbour Lane, Portsea"}, "ts": "2026-10-10T08:47:30.345667+00:00"}
```

`get_order` and `list_open_orders` are idempotent reads; `ship_replacement`, the
non-idempotent tool, ran exactly once.

## Model calls and prompt caching (R10.3, R18.6)

One `chat gpt-6.1-sol` span per `invoke_llm` activity run (16 of each). From
the second call on, the static prefix (system prompt, participants, skills index, tool
definitions) is served from the provider's cache: `cached_tokens` in the usage response
is non-zero.

| Call | input tokens | cached input tokens | output tokens |
|---|---|---|---|
| 1 | 1873 | 0 | 116 |
| 2 | 2091 | 1759 | 19 |
| 3 | 2891 | 1759 | 23 |
| 4 | 3146 | 2888 | 23 |
| 5 | 3344 | 3143 | 144 |
| 6 | 3554 | 1759 | 24 |
| 7 | 4021 | 3551 | 119 |
| 8 | 4250 | 1759 | 96 |
| 9 | 4474 | 1759 | 299 |
| 10 | 4827 | 4471 | 129 |
| 11 | 5152 | 4824 | 79 |
| 12 | 5416 | 5149 | 109 |
| 13 | 5645 | 1759 | 33 |
| 14 | 5781 | 5642 | 71 |
| 15 | 5955 | 1759 | 20 |
| 16 | 5655 | 1759 | 49 |

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
| 10 | `ask_participant` |
| 11 | `ask_participant` |
| 12 | `complete_step` |
| 13 | `demo-support/orders.ship_replacement` |
| 14 | `complete_step` |
| 15 | `unload_skill` |

## Final task (`GetTask`, with the task extension in `metadata`)

```json
{
  "id": "96086ae3-a399-4ba3-9c00-c2057b0ecbbc",
  "contextId": "ctx-1826d76e",
  "status": {
    "state": "TASK_STATE_COMPLETED",
    "message": {
      "messageId": "96086ae3-a399-4ba3-9c00-c2057b0ecbbc:status:7",
      "contextId": "ctx-1826d76e",
      "taskId": "96086ae3-a399-4ba3-9c00-c2057b0ecbbc",
      "role": "ROLE_AGENT",
      "parts": [
        {
          "text": "Your replacement blender for order #48213 is shipping to 14 Harbour Lane, Portsea; tracking number: **NB-48213-R1**. No refund was issued, and order #48377 was left unchanged."
        }
      ]
    },
    "timestamp": "2026-10-10T08:47:39.577279Z"
  },
  "metadata": {
    "io.github.madarauchiha-314.tiny-harness/task": {
      "description": "",
      "participants": [
        {
          "display_name": "",
          "id": "alice",
          "kind": "human",
          "role": "reporter"
        },
        {
          "display_name": "",
          "id": "tiny-harness",
          "kind": "agent",
          "role": "assignee"
        }
      ],
      "name": "Refund order #48213: the customer says the blender arrived c",
      "goal": "Refund order #48213: the customer says the blender arrived cracked. Check the order and propose a resolution.",
      "acceptance_criteria": [],
      "plan": {
        "steps": [
          {
            "output": "Verified order #48213: Nimbus 900 blender, $129, delivered October 6, 2026, warranty active until October 6, 2027, shipping address 14 Harbour Lane, Portsea. Open orders also include #48377, a travel cup with a different shipping address (3 Quay Street, Portsea); any replacement address must be confirmed.",
            "depends_on": [],
            "id": "verify-the-order",
            "linked_tasks": [],
            "description": "Verify order details and check the customer's open orders.",
            "name": "verify the order",
            "state": "done"
          },
          {
            "output": "The damaged-on-arrival policy allows a customer-selected refund or replacement within 14 days of delivery. A $129 refund requires a damage photo first; a replacement does not. Eligibility is conditional on confirmation that the damage was reported within 14 days of October 6, 2026, as no reporting date is available. No refund or shipment has been made.",
            "depends_on": [
              "verify-the-order"
            ],
            "id": "apply-the-policy",
            "linked_tasks": [],
            "description": "Identify eligibility, the 14-day damage reporting window, and photo requirement for a $129 refund.",
            "name": "apply the policy",
            "state": "done"
          },
          {
            "output": "Alice changed the selected resolution from refund to replacement and explicitly authorized shipment for order #48213 to 14 Harbour Lane, Portsea. She confirmed the crack was reported on October 6, 2026, the delivery date, satisfying the 14-day window, and that order #48377 is unrelated. No photo is required for replacement under the policy.",
            "depends_on": [
              "apply-the-policy"
            ],
            "id": "agree-the-resolution-with-the-customer",
            "linked_tasks": [],
            "description": "Present refund and replacement options via A2UI and obtain the reporter's decision and required evidence or address confirmation.",
            "name": "agree the resolution with the customer",
            "state": "done"
          },
          {
            "output": "Shipped the authorized replacement for order #48213 to 14 Harbour Lane, Portsea under the damaged-on-arrival policy; tracking number NB-48213-R1. No refund was issued and order #48377 was not changed.",
            "depends_on": [
              "agree-the-resolution-with-the-customer"
            ],
            "id": "record-the-resolution",
            "linked_tasks": [],
            "description": "Execute only a confirmed eligible resolution and record its result.",
            "name": "record the resolution",
            "state": "done"
          }
        ]
      },
      "parent_tasks": [],
      "sub_tasks": [],
      "type": null
    }
  }
}
```

## Trace

[`e2e/trace.json`](e2e/trace.json): the 250 GenAI, MCP and Temporal activity
spans of the run (the polling `events_since` query spans are omitted), one object per
span with `trace_id`, `span_id`, `parent_id`, `start`, `end`, `status` and the redacted
attributes. The JSON-lines exporter wrote them to the run's `trace.jsonl`
(`o11y.trace_file`).
