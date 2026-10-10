# Capability: a2a-server

> The harness is an A2A 1.0 server on the official SDK, every verb over JSON-RPC and
> HTTP+JSON, streaming from the workflow's durable event log; `SendMessage` is the inbox.

## What it is

The inbound half of A2A and the only API. A request never runs the core loop: `execute`
update-with-starts the task's workflow and streams its event log back; the inbox is the
workflow's mailbox. Lives in `tiny_harness/service/a2a/` and `service/inbox.py`.

## Current behaviour

- The server SHALL serve A2A 1.0 with `a2a-sdk`'s routes over the JSON-RPC and HTTP+JSON
  bindings: `SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`,
  `SubscribeToTask`, the four push-notification config operations and
  `GetExtendedAgentCard`. No gRPC.
- The agent card at `/.well-known/agent-card.json` SHALL be built from the agent's
  description, so every extension (task, channel, A2UI with its catalog ids) reaches
  `capabilities.extensions`; it declares no security scheme (decision-003) and is pinned
  by a contract snapshot.
- WHEN `A2A-Extensions` names an extension the card does not advertise THEN the request
  SHALL be rejected with the unsupported-operation error and no task created.
- WHEN `execute` runs THEN it SHALL redact the message, update-with-start the task's
  `TaskWorkflow` with the message as the `inbox` update, and stream the workflow's event
  log from the receipt's cursor into the SDK's queue: the `Task` first, then status and
  artifact updates. A first message names no task; the server assigns the id.
- `returnImmediately: true` SHALL return once the task and the inbox item exist. A
  message SHALL be persisted (the inbox audit row) before the request is acknowledged.
- WHEN `cancel` runs THEN the workflow SHALL be signalled and the task emitted as
  `CANCELED`.
- `SubscribeToTask` SHALL replay the event log from sequence 1, across server restarts.
- Partial progress SHALL be streamed: every status update, the A2UI artifact updates and
  channel message events, not one terminal event per turn.
- `GetTask` SHALL answer from the workflow's `task` query, falling back to the store once
  the workflow is gone; every task operation SHALL apply one access policy: with
  `X-Participant-Id` set, a task the participant is not on is not found.
- Push-notification configs SHALL be stored with their token encrypted and every status
  update delivered to them from the `emit_event` activity with the
  `X-A2A-Notification-Token` header.
- Every route SHALL sit behind the limits middleware: a body over `max_request_bytes` is
  413 and a peer over `rate_limit_per_minute` is 429, before anything reaches Temporal.
- `GET /_monitor` SHALL return the last heartbeat snapshot; with `ui_dir` set the built
  web renderer is served under `/ui`; `cors_origins` enables CORS for a dev renderer.

## Design

[design.md § A2A server](../specs/issue-3/design.md#a2a-server-r14--servicea2a),
[design.md § Inbox and events](../specs/issue-3/design.md#inbox-and-events-r15--serviceinboxpy),
[decision-002](../decisions/decision-002.md), [decision-003](../decisions/decision-003.md),
[A2A extensions](../a2a/extensions).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Executor, handler, card, bridge, task store, push, limits, inbox intake (Layer 5); A2UI params on the card (Layer 7); `/ui` and CORS (Layer 8) | [spec](../specs/issue-3/), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11), [PR #13](https://github.com/MadaraUchiha-314/tiny-harness/pull/13), [PR #14](https://github.com/MadaraUchiha-314/tiny-harness/pull/14) |
