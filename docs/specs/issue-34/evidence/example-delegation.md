# Evidence: the delegation example with a real model (T13)

> R5 and R6, added in PR review. Run on 2026-10-13 with `gpt-6.1-sol`, both agents on
> `127.0.0.1`, embedded Temporal, `TEMPORAL_API_KEY` unset, `OPENAI_API_KEY` from the
> environment (not recorded). Task ids are shortened.

**Result: pass.** The front desk had no tools and was told nothing about the ledger. Its
model read the ledger's card, delegated the question by itself, and answered with facts
that only the ledger's tool holds.

## Procedure

As in `testing-plan.md` § Verification environment (T13). Each server was started from a
script file and stopped by process group:

```sh
uv run tiny-harness --config examples/delegation/ledger.toml serve      # :8091
uv run tiny-harness --config examples/delegation/front-desk.toml serve  # :8090
```

The question was sent to the front desk as one JSON-RPC `SendMessage` with
`X-Participant-Id: alice`: *"What is the status of order 48213?"*

## 1. The ledger serves the card that `[card]` configures (R5.2)

`GET http://127.0.0.1:8091/.well-known/agent-card.json` (excerpt):

```json
{
  "name": "Order ledger",
  "description": "Answers questions about the status of a Nimbus Kitchen order: shipping, delivery and refunds. Give it the order number.",
  "version": "0.1.0"
}
```

## 2. The front desk lists the ledger at start

Front-desk log, at startup:

```json
{"level": "INFO", "logger": "tiny_harness.runtime", "msg": "agents roster: ledger"}
```

No truncation warning: the ledger's card is within the caps.

## 3. The front desk delegates, unprompted (R6.2)

The first status reply to the user: *"I'm checking the order ledger for the latest status
of order 48213."* The front-desk task's `sub_tasks`:

```json
[{"task_id": "cd675ce4….1", "agent": {"kind": "agent", "id": "ledger"}, "state": "COMPLETED"}]
```

The ledger's task (read with `GetTask` as the front desk's identity, `tiny-harness`):

- **goal:** "Look up Nimbus Kitchen order 48213 and report its current status, carrier,
  shipping and delivery dates, and any refund information available."
- The ledger called its `ledger/orders.get_order` tool (`tool.invoked` pre/post in its
  log), then answered:
  *"Order **48213** (Nimbus 900 blender) is **shipped** via **Harbour Couriers**, with a
  shipping date of **October 10, 2026** and expected delivery on **October 14, 2026**.
  The ledger has no actual delivery date or refund information recorded."*

## 4. The front desk answers with the ledger's result

The front-desk task's final status message:

> Order **48213** (Nimbus 900 blender) has **shipped**.
>
> - **Carrier:** Harbour Couriers
> - **Shipped:** October 10, 2026
> - **Expected delivery:** October 14, 2026
>
> The ledger has no confirmed delivery date or refund information recorded.

The carrier and the dates exist only in `examples/delegation/ledger/mcp_ledger.py`, which
the front desk cannot reach. The front desk's plan recorded both steps as `done`
("Check order", then "Report status").

## Observations

- One attempt, no retries.
- Not part of this change: both agents name themselves `tiny-harness` as a participant,
  so the ledger's task lists `tiny-harness` as both reporter and assignee. This is the
  existing participant id, which `[card]` does not change.
