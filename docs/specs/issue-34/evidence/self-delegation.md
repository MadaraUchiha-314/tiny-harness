# Evidence: the harness delegates to itself with a real model (T15)

> R7, added in PR review. Run on 2026-10-13 with `gpt-6.1-sol`, on the code of
> `ad69377`: one harness, `examples/delegation/ledger.toml`, on `127.0.0.1:8091` with
> embedded Temporal. `TEMPORAL_API_KEY` was unset; `OPENAI_API_KEY` came from the
> environment and is not recorded. Task ids are shortened.

**Result: pass.** The model was asked a two-part question and was not told about
sub-tasks. It chose by itself to run each part as a sub-task on itself (`agent` null, so
`self`), and gave each a name, a goal, a description and acceptance criteria. Each child
was created through the harness's own A2A interface, ran in a clean context, finished by
itself, and its answer came back to the parent, which combined them.

## Procedure

```sh
uv run tiny-harness --config examples/delegation/ledger.toml serve   # :8091
```

At startup the log says `agents roster: self`. One JSON-RPC `SendMessage` as `alice`:

> Look into orders 48213 and 48377 one at a time, each on its own, and then tell me which
> of them needs a follow-up from us and why.

Then `GetTask` on the parent as `alice`, and on each child as the harness's own
participant id (`tiny-harness`), which is the only participant of a child.

## 1. The parent spawns two sub-tasks on itself

The parent's first status: *"I'm checking order 48213 on its own first, then I'll check
48377 and compare which needs follow-up."* Its `sub_tasks` at the end:

| Row `task_id` | `agent` | State |
|---------------|---------|-------|
| `44298f5d…` | none: on this harness | `COMPLETED` |
| `9d05494a…` | none: on this harness | `COMPLETED` |

Each row names the child's own A2A task on this server (R7.4), not a local workflow id.

## 2. Each child is a full brief, and nothing else (R7.2, R7.7)

`GetTask` on each child, from its task extension:

| | Child 1 | Child 2 |
|-|---------|---------|
| `name` | Check order 48213 | Check order 48377 |
| `goal` | Look up Nimbus Kitchen order 48213 and report ledger facts and any indication it needs follow-up. | Look up Nimbus Kitchen order 48377 independently and report ledger facts and any indication it needs follow-up. |
| `description` | Investigate only order 48213 independently using the order ledger. Do not change the order. Report its status, shipping/delivery/refund details and any unresolved issue. Distinguish facts from inference. | Investigate only order 48377 using the order ledger. Do not change the order. Report its status, shipping/delivery/refund details and any unresolved issue. Distinguish recorded facts from inference. |
| `acceptance_criteria` | Look up order 48213 using the ledger. · Provide ledger facts supporting any follow-up recommendation. | Look up order 48377 using the ledger. · Provide ledger facts supporting any follow-up recommendation. |
| `lifecycle` | `delegated` | `delegated` |
| `parent_tasks` | the parent | the parent |
| `participants` | `tiny-harness` (assignee) | `tiny-harness` (assignee) |
| State | `COMPLETED` | `COMPLETED` |

- `alice` is not a participant of either child, and the parent's conversation is not in
  either: each ran in a clean context.
- `lifecycle: delegated` came from the brief, which the server accepted because the
  sender is the harness itself (the `[server] delegators` rule).
- The harness's log shows 17 model calls and 12 tool calls (`get_order` and the
  intrinsics such as `spawn_subtask`) across the three tasks.

## 3. The parent answers with both results (R7.5)

> **Order 48213 is the follow-up candidate if its expected delivery date of October 14,
> 2026 has passed and receipt remains unconfirmed:** it shipped via Harbour Couriers on
> October 10, but the ledger has no delivery confirmation or recorded issue. **Order 48377
> needs no follow-up based on the ledger:** its $24.00 refund was recorded on October 9,
> 2026, with no unresolved issue listed.

The carrier, the dates and the refund come from the children's `get_order` results.

## Observations

- The model ran the two children one after the other, as the user asked ("one at a
  time"), not in parallel.
- One attempt, no retries.
