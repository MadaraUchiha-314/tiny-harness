---
name: support-agent
description: How to resolve a customer complaint about an order within policy, step by step.
---

# Support agent playbook

Use this playbook for any complaint about an order.

1. Call `demo-support/orders.get_order` with the order id from the complaint. Note the item, price,
   delivery date, warranty and shipping address.
2. Call `demo-support/policy.lookup` with the complaint's topic (for example `damaged on arrival`).
3. Create a plan with `create_plan` whose steps are: verify the order, apply the policy,
   agree the resolution with the customer, record the resolution. Mark each step with
   `complete_step` as you finish it.
4. Present the resolution options to the reporter as an A2UI card with `emit_ui`: a
   `createSurface` message with `catalogId`
   `https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json`, then an
   `updateComponents` message whose root is a `Card` containing a `Column` of a `Text`
   title, a `ChoicePicker` (`value: {"path": "/choice"}`) with one option per policy
   outcome, and a `Button` whose `action.event` is named `confirm` with context
   `{"choice": {"path": "/choice"}}`.
5. Whenever the policy leaves a judgement call open, or the customer has more than one
   open order (check `demo-support/orders.list_open_orders`), ask the reporter with
   `ask_participant` before acting; never guess an address or a preference.
6. After the reporter's reply, act with `demo-support/orders.refund` or `demo-support/orders.ship_replacement` as
   agreed, complete the remaining steps, and answer with a two-sentence summary.
