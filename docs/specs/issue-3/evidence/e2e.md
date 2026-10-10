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
3 passed in 254.55s (0:04:14)
```

## Transcript (`tests/e2e/test_demo.py`)

```text
[   5.6s] task           TASK_STATE_SUBMITTED     78693213-fea8-445e-9052-1a2c009ed35a
[   5.6s] status_update  TASK_STATE_WORKING       
[  42.4s] artifact_update                          a2ui
[  46.3s] status_update  TASK_STATE_INPUT_REQUIRED Please confirm this concerns the $129 Nimbus 900 blender, order #48213 (not travel cup #48377), and tell me when the damage was reported so I can verify the 14-day window after October 6, 2026 delivery. Would you like the $129 refund or a replacement? For a refund, please provide a photo of the crack first; for a replacement, please confirm the shipping address (the blender was sent to 14 Harbour Lane, Portsea, while the other order has a different address).
[  46.8s] status_update  TASK_STATE_WORKING       
[  51.1s] status_update  TASK_STATE_INPUT_REQUIRED You selected the $129 refund for blender order #48213. Before I can issue it, please provide a photo of the crack and the date the damage was reported, so I can verify it was within 14 days of delivery on October 6, 2026; please also confirm that #48213 is the affected order.
[  51.9s] status_update  TASK_STATE_WORKING       
[  69.2s] status_update  TASK_STATE_COMPLETED     Your replacement for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking **NB-48213-R1**. As requested, no refund was issued, and order #48377 was left unchanged.
```

The flow of requirement 24: plan, `gpt-6.1-sol`, MCP tools, an A2UI card (artifact
`a2ui`, basic catalog), a help request answered over two turns, a terminal state.

## Orders ledger (the MCP server's audit file)

```text
{"tool": "get_order", "arguments": {"order_id": "48213"}, "ts": "2026-10-10T05:15:31.634697+00:00"}
{"tool": "list_open_orders", "arguments": {"order_id": "48213"}, "ts": "2026-10-10T05:15:44.269093+00:00"}
{"tool": "ship_replacement", "arguments": {"order_id": "48213", "address": "14 Harbour Lane, Portsea"}, "ts": "2026-10-10T05:16:14.818994+00:00"}
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
| 1 | 1873 | 0 | 117 |
| 2 | 2091 | 1759 | 35 |
| 3 | 2891 | 1759 | 23 |
| 4 | 3146 | 2888 | 23 |
| 5 | 3344 | 3143 | 143 |
| 6 | 3539 | 1759 | 24 |
| 7 | 4006 | 3536 | 101 |
| 8 | 4239 | 1759 | 77 |
| 9 | 4424 | 1759 | 291 |
| 10 | 4769 | 4421 | 130 |
| 11 | 5095 | 4766 | 90 |
| 12 | 5381 | 5092 | 99 |
| 13 | 5611 | 1759 | 33 |
| 14 | 5747 | 5608 | 75 |
| 15 | 5929 | 1759 | 35 |
| 16 | 5629 | 1759 | 50 |

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
  "id": "78693213-fea8-445e-9052-1a2c009ed35a",
  "contextId": "ctx-0c530a66",
  "status": {
    "state": "TASK_STATE_COMPLETED",
    "message": {
      "messageId": "78693213-fea8-445e-9052-1a2c009ed35a:status:7",
      "contextId": "ctx-0c530a66",
      "taskId": "78693213-fea8-445e-9052-1a2c009ed35a",
      "role": "ROLE_AGENT",
      "parts": [
        {
          "text": "Your replacement for order #48213 is shipping to 14 Harbour Lane, Portsea, with tracking **NB-48213-R1**. As requested, no refund was issued, and order #48377 was left unchanged."
        }
      ]
    },
    "timestamp": "2026-10-10T05:16:24.407490Z"
  },
  "metadata": {
    "io.github.madarauchiha-314.tiny-harness/task": {
      "plan": {
        "steps": [
          {
            "depends_on": [],
            "output": "Order #48213 is a $129 Nimbus 900 blender, delivered October 6, 2026, with warranty active until October 6, 2027, shipped to 14 Harbour Lane, Portsea. Another open order, #48377, is a travel cup shipped to a different address, 3 Quay Street, Portsea; reporter confirmation is needed before acting.",
            "description": "Verify order details and check the customer's open orders.",
            "name": "verify the order",
            "linked_tasks": [],
            "id": "verify-the-order",
            "state": "done"
          },
          {
            "depends_on": [],
            "output": "The damaged-on-arrival policy allows a refund or replacement within 14 days of delivery. A $129 refund requires a damage photo first; a replacement does not. The reporting date and photo have not been established, so eligibility and customer preference must be confirmed before action.",
            "description": "Determine applicable damaged-arrival outcomes and requirements.",
            "name": "apply the policy",
            "linked_tasks": [],
            "id": "apply-the-policy",
            "state": "done"
          },
          {
            "depends_on": [
              "verify-the-order",
              "apply-the-policy"
            ],
            "output": "Alice changed the selected resolution from refund to replacement and explicitly authorized shipping a replacement for order #48213 to 14 Harbour Lane, Portsea. She confirmed the crack was reported October 6, 2026, the delivery date, satisfying the 14-day policy, and that order #48377 is unrelated. No damage photo is required for a replacement.",
            "description": "Present refund and replacement choices and obtain preference, eligibility confirmation and any required photo or address confirmation.",
            "name": "agree the resolution with the customer",
            "linked_tasks": [],
            "id": "agree-the-resolution-with-the-customer",
            "state": "done"
          },
          {
            "depends_on": [
              "agree-the-resolution-with-the-customer"
            ],
            "output": "Shipped the reporter-authorized replacement for order #48213 to 14 Harbour Lane, Portsea under the damaged-on-arrival policy. The shipment tool confirmed tracking NB-48213-R1; no refund was issued and order #48377 was untouched.",
            "description": "Execute only the eligible, explicitly approved resolution and record the result.",
            "name": "record the resolution",
            "linked_tasks": [],
            "id": "record-the-resolution",
            "state": "done"
          }
        ]
      },
      "participants": [
        {
          "id": "alice",
          "kind": "human",
          "role": "reporter",
          "display_name": ""
        },
        {
          "id": "tiny-harness",
          "kind": "agent",
          "role": "assignee",
          "display_name": ""
        }
      ],
      "name": "Refund order #48213: the customer says the blender arrived c",
      "type": null,
      "goal": "Refund order #48213: the customer says the blender arrived cracked. Check the order and propose a resolution.",
      "description": "",
      "sub_tasks": [],
      "acceptance_criteria": [],
      "parent_tasks": []
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
