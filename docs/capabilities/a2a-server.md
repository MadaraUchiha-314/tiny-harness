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
  description: the name, description, version and skills set in `[card]`, or the
  built-in defaults where unset (issue-34), so every extension (task, channel, status, commands with the registered
  commands in its `params`, A2UI with its catalog ids) reaches
  `capabilities.extensions`; the command registry is frozen and published before the
  card is built; it declares no security scheme (decision-003) and is pinned
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
  `CANCELED`. A `watcher` SHALL be refused with the unsupported-operation error.
- A message, completion or cancellation for a task in a terminal state SHALL be refused
  with an error naming the state (`the task is in a terminal state
  (TASK_STATE_COMPLETED)`), and the task left unchanged.
- WHEN a message's one data part is the `control` envelope `{"kind": "control",
  "action": "complete"}` THEN the server SHALL complete the task
  ([extensions](../a2a/extensions#completing-a-task)): the inbox update's validator
  refuses a sender who is missing, not on the task or only a `watcher` before anything
  is interrupted; the control then bypasses the SDK's per-task request queue so it can
  cut a running turn, and the stream ends `COMPLETED`, or `INPUT_REQUIRED ·
  awaiting-next-message` when an unresolved sub-task refuses it.
- WHEN a message is exactly `/<name> <arguments>` for a registered command THEN the
  workflow's dispatcher SHALL run it through the `run_command` activity before (or, mid
  turn, between) model calls, never invoking the model for it; the reply arrives as the
  message of a re-emitted status update with metadata `{"command": "<name>"}` (and
  `"task_ref"` for a created sub-task), and the state is unchanged. Commands and
  controls skip `request.received`; `command.invoked` is their policy point. An
  unregistered `/<name>` is an ordinary message. A command or refused message as a
  task's first message parks the task instead of re-emitting `SUBMITTED`.
- `SubscribeToTask` SHALL replay the event log from sequence 1, across server restarts,
  then stay attached for live events, ending only at a terminal state (A2A 1.0), so a
  subscriber to a parked (`INPUT_REQUIRED`) conversation sees what happens next.
  A `SendMessage` stream still ends at the newest final event, `INPUT_REQUIRED` included.
- A `task` event envelope on an existing task SHALL update its name, description and
  acceptance criteria for any participant and its participants only for an admin
  (refused otherwise); a `status_update` or `artifact_update` envelope SHALL be recorded
  into the task's history as a framed event with an audit row. Routing such updates to
  a remote sub-task is not built in this work item.
- Partial progress SHALL be streamed: every status update, the A2UI artifact updates and
  channel message events, not one terminal event per turn.
- `GetTask` SHALL answer from the workflow's `task` query, falling back to the store once
  the workflow is gone; every task operation SHALL apply one access policy: with
  `X-Participant-Id` set, a task the participant is not on is not found.
- Push-notification configs SHALL be stored with their token encrypted and every status
  update delivered to them from the `emit_event` activity with the
  `X-A2A-Notification-Token` header.
- `POST /a2a/push/{task_id}` SHALL receive a remote task's push for its local stand-in
  (issue-27). A body over 64 KiB is `413` and an unparseable one `400`. A missing or
  wrong `X-A2A-Notification-Token`, an id that names no stand-in or an ended one, or a
  body naming another remote task is `401`, all alike. Only a push whose token digest
  matches, checked in constant time by the `remote_push` update's validator, wakes the
  stand-in (`204`). The SDK's DEBUG log of JSON-RPC request bodies is dropped, since a
  body can carry a push token.
- Every route SHALL sit behind the limits middleware: a body over `max_request_bytes` is
  413 and a peer over `rate_limit_per_minute` is 429, before anything reaches Temporal.
- A `Harness` (`tiny_harness/service/harness.py`) SHALL serve the agent without opening a
  port: `asgi_app()` is the app a host mounts and exists from construction. WHILE the
  harness is not started, every request SHALL be `503` and reach no route. WHEN the app is
  mounted somewhere other than its prefix THEN every request SHALL be `500` naming both
  paths. As the top-level app it SHALL start its harness from the `lifespan` scope.
  `running_harness` is a `Harness` behind its own uvicorn, with `root_path` set to the
  prefix.
- The routes SHALL be built before start over a `DeferredRequestHandler` and the card
  through `card_modifier`, so they can be mounted early and listed in OpenAPI.
  `tiny_harness.fastapi.harness_router(harness)` SHALL return an `APIRouter` with the
  harness's lifespan and prefix, its routes tagged `A2A: <agent id>`. The 503 gate, the
  prefix check and the limits are router dependencies there, and CORS and `/ui` are not
  served (a warning names each).
- The card and the push callback SHALL carry `public_url`: `base_url` with the mount
  prefix. A prefix that disagrees with `base_url`'s path is a `ConfigError`.
  `RouteOptions` SHALL turn off the limits, CORS, `/_monitor`, the push route (the agent
  then follows remote tasks) and `/ui` one by one.
- WHEN a participant resolver is given THEN the participant SHALL come from it only, the
  `X-Participant-Id` header SHALL be ignored, and a message with no resolved participant
  SHALL be refused even when its metadata names one. A resolver that raises fails the
  request.
- A task SHALL belong to the agent whose task queue runs its workflow. `TemporalTaskStore`
  describes the workflow first (cached per id), and a foreign queue is answered as an
  unknown id. `ListTasks` filters on `TaskQueue`, and the `context_id` in that query is
  quoted. `PushReceiver` answers `401` for a stand-in on another queue.
- `GET /_monitor` SHALL return the last heartbeat snapshot; with `ui_dir` set the built
  web renderer is served under `/ui`; `cors_origins` enables CORS for a dev renderer.
- WHEN a new task's first message carries a `task` envelope THEN the server SHALL build
  the task from it, add the sender as reporter when it is not on the task, and remove the
  envelope from the message so intake does not apply it again. `lifecycle`, `model` and
  `reasoning_effort` SHALL be accepted only from a trusted delegator — this agent itself,
  or an id in `[server] delegators` — and refused whole from anyone else; an existing
  task keeps refusing them from everyone (issue-34 R7, abuse cases 5–7).
- WHEN the brief names an assignee other than this agent THEN the task SHALL run in
  participant mode (no model call; it waits for its assignee). WHEN the first message is
  the brief alone THEN the task SHALL start with no message for its model: a
  conversation parks awaiting its first message (issue-34 R7.2).
- WHEN `[media]` is set THEN the card's `defaultInputModes` and `defaultOutputModes`
  SHALL list the effective media types and the card SHALL declare the media extension v1
  (`docs/a2a/ext/media/v1.md`) with the types, the limits, which services are on and the
  media path; without `[media]` the card is unchanged. The commands extension lists a
  surface command with `runsOn: "surface"`.
- `execute` SHALL extract the new turn's file parts through `MediaIntake` after the
  access check and before redaction, so the workflow and the redactor never see base64;
  a refusal answers `InvalidParams` with the code and the limit. `GET
  /media/{task_id}/{media_id}` is mounted with the harness's routes
  (`RouteOptions.media`) and the request cap grows to admit a full message of media.

## Design

[design.md § A2A server](../specs/issue-3/design.md#a2a-server-r14--servicea2a),
[design.md § Inbox and events](../specs/issue-3/design.md#inbox-and-events-r15--serviceinboxpy),
[decision-002](../decisions/decision-002.md), [decision-003](../decisions/decision-003.md),
[A2A extensions](../a2a/extensions).
[issue-38 design.md § A2A surface](../specs/issue-38/design.md#components-interfaces).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Executor, handler, card, bridge, task store, push, limits, inbox intake (Layer 5); A2UI params on the card (Layer 7); `/ui` and CORS (Layer 8) | [spec](../specs/issue-3/), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11), [PR #13](https://github.com/MadaraUchiha-314/tiny-harness/pull/13), [PR #14](https://github.com/MadaraUchiha-314/tiny-harness/pull/14) |
| issue-25 | Status and commands extensions on the card; the `control` completion envelope; terminal and watcher refusals naming the state; slash commands dispatched in the workflow with the reply on a re-emitted status update | [spec](../specs/issue-25/), [PR #26](https://github.com/MadaraUchiha-314/tiny-harness/pull/26), [decision-007](../decisions/decision-007.md) |
| issue-27 | `POST /a2a/push/{task_id}` for remote tasks' pushes; the SDK's request-body DEBUG log dropped | [spec](../specs/issue-27/), [PR #28](https://github.com/MadaraUchiha-314/tiny-harness/pull/28) |
| issue-34 | The card's name, description, version and skills come from `[card]` | [spec](../specs/issue-34/), [PR #35](https://github.com/MadaraUchiha-314/tiny-harness/pull/35) |
| issue-34 (R7) | A new task built from its creator's brief: trusted delegators (`[server] delegators`, this agent always), participant mode for an assignee other than this agent, a brief-only start | [spec](../specs/issue-34/), [PR #35](https://github.com/MadaraUchiha-314/tiny-harness/pull/35) |
| issue-36 | `Harness` and `asgi_app()` mounted on a host app (503 before start, mount check, lifespan); routes built before start; `tiny_harness.fastapi.harness_router`; `public_url` in the card and push URL; `RouteOptions`; the participant resolver with strict mode; task and push ownership by queue | [spec](../specs/issue-36/), [PR #37](https://github.com/MadaraUchiha-314/tiny-harness/pull/37), [decision-009](../decisions/decision-009.md) |
| issue-38 | Media intake in `execute`, the media route, the card's media modes and the media extension v1, `runsOn` in the commands extension | [spec](../specs/issue-38/), [PR #39](https://github.com/MadaraUchiha-314/tiny-harness/pull/39), [decision-010](../decisions/decision-010.md) |
