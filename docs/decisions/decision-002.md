# Decision 002: Temporal owns the whole request lifecycle

- **Status:** proposed (accepted when the issue-3 design is approved)
- **Date:** 2026-10-09
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #3](https://github.com/MadaraUchiha-314/tiny-harness/issues/3)

## Context

Requirement 19 asks for durable execution on Temporal, and the approver answered the
ticket's open question with "Temporal in the whole request lifecycle", not only the core
loop. The A2A SDK calls `AgentExecutor.execute` inside an HTTP request and expects task
events on an event queue in that process. Something has to connect a durable workflow,
which may outlive the request and the process, to that queue.

## Decision

1. **One Temporal workflow per harness task**, workflow id = task id. The workflow holds
   the task, plan, state and conversation history and runs the core loop; every
   side-effecting or non-deterministic operation is an activity.
2. **The inbox is the workflow's mailbox.** `execute` turns an inbound A2A message into
   an update-with-start on the task workflow: the message is durable in Temporal history
   before the request is acknowledged, a new task starts its workflow, and an existing
   task receives the message as an update. No separate queue.
3. **Heartbeat is a Temporal schedule** that starts a short heartbeat workflow at the
   configured interval: it polls pull-based channels, signals the task workflows that
   have pending items, and emits the monitoring snapshot.
4. **The event bridge is an interface with a polling default.** The executor polls the
   workflow's `events_since(cursor)` query and forwards each event to the A2A event queue
   until the task is final or the client disconnects. A broker-backed bridge can replace
   it through the registry without touching the workflow.
5. **Channel delivery and persistence writes are activities**, so they inherit retries
   and are replayed from history after a crash.

## Consequences

- A crash anywhere between request receipt and terminal state loses nothing: the
  message, every LLM and tool result, and every emitted event are in history.
- Streaming latency equals the polling interval of the bridge (design default 250 ms).
- The A2A SDK's task store becomes a read model over workflow queries and visibility
  search attributes rather than the source of truth.
- Long conversations need continue-as-new; the workflow carries its state across it.
- Temporal is a hard dependency of the server, including for local development (the
  Temporal CLI dev server or the SDK's test environment).

## Alternatives considered

- **Temporal for the core loop only, inbox in the persistence store** — two durability
  mechanisms with a hand-written bridge between them; the approver chose otherwise.
- **A message broker for the event bridge** — a second piece of infrastructure for a
  latency gain the demo does not need; kept as a plugin option.
- **Running the loop inside the HTTP request** — no durability, violates Requirement 14.5.
