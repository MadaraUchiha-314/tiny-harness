# Capability: remote-agents

> The harness delegates to other A2A 1.0 agents through the official client, as sub-tasks
> tracked by their A2A status.

## What it is

The outbound half of A2A. A remote agent is registered from configuration, its card is
fetched and validated, and a delegation becomes a child workflow that drives the remote
task and reports back. Lives in `tiny_harness/harness/agents/` and the
`RemoteTaskWorkflow` of `tiny_harness/service/durable/`.

## Current behaviour

- The system SHALL talk to remote agents at A2A 1.0 through `a2a-sdk`'s client, sending
  `A2A-Version: 1.0` on every request.
- WHEN a remote agent is registered (`agents = [{id, url, version}]`) THEN its card SHALL
  be fetched from `/.well-known/agent-card.json` and validated before anything is sent.
  A card that declares a security scheme or requires an extension the harness does not
  implement SHALL be refused with `UnsupportedExtensionError` and the reason recorded.
- WHEN a registered agent's URL is on the harness's own origin (an agent in the same
  service) THEN its card SHALL be fetched and validated on first use, not at start. The
  service is not listening while it starts. Calls still go over HTTP through the other
  agent's routes.
- `A2A-Extensions` SHALL name only extensions the remote card advertises.
- WHEN the harness starts THEN it SHALL build an agents roster from the registered
  agents' cards (id, name, description, up to 10 skills; never the URL), sorted by id.
  Each field is flattened to one line, `<`/`>` become `‹`/`›`, and long fields are cut
  with `…` (name 80, description 500, skill description 200 characters), with one
  `WARNING` per cut. The roster is the context window's `agents` section, and the ids
  are logged at `INFO` (issue-34).
- IF `spawn_subtask` names an `agent` that is not registered (an empty string included)
  THEN it SHALL return an `agent.unknown` error listing the valid ids, and no sub-task
  SHALL be created (issue-34).
- WHEN the harness delegates (`spawn_subtask` naming a remote agent) THEN a sub-task
  SHALL be created, linked to the remote A2A task id, and tracked through the remote
  task's status updates, including `INPUT_REQUIRED` and `AUTH_REQUIRED`; the child
  workflow signals the parent when it is done, and the parent SHALL NOT complete while a
  sub-task is unresolved.
- WHILE a remote sub-task is parked (`INPUT_REQUIRED`, `AUTH_REQUIRED`) its stand-in
  SHALL watch it, per the agent's `updates` setting:
  - **push** (`auto`, when the card advertises push and `server.base_url` is set): the
    stand-in registers `<base_url>/a2a/push/<local task id>` with a 256-bit random token
    on the remote task. A verified push only wakes the stand-in, which fetches the task
    with `GetTask` and applies that state, never the push body. It fetches again after 1,
    2 and 4 s while the fetch disagrees with the state the push claims. The harness keeps
    only the token's SHA-256 digest.
  - **follow** (`follow`, or `auto` without push, or a failed registration): a
    heartbeating activity holds `SubscribeToTask` open, re-subscribing after
    `follow_interval` when a stream ends unchanged; a reply or a cancel cancels it.
  - **off**: nothing between turns, as before.
- A change heard between turns SHALL update the parent's sub-task row; the parent's
  model SHALL be told only of a terminal state or a new `INPUT_REQUIRED`/`AUTH_REQUIRED`,
  never of `WORKING`.
- WHEN a stand-in ends (a terminal state, or cancelled) THEN it SHALL delete its push
  config from the remote task, best effort; later pushes with its token are refused.
- Every call the stand-in makes on the remote task SHALL assert `X-Participant-Id` with
  the id it delegated as, so a tiny-harness peer answers it (decision-003).
- The harness itself SHALL be registered as the agent `self`: a `RemoteAgent` built from
  its own card (`[card]`) at its own `server.base_url`, reached over HTTP like any remote
  agent, with nothing fetched at startup. A configured agent SHALL NOT use the id `self`
  (issue-34 R7.1). An in-process transport is a later optimisation behind the same
  interface.
- WHEN a child is created on an agent THEN the `start_agent_task` activity SHALL send its
  brief with `SendMessage` (a text part and, when the card advertises the task extension,
  a task envelope), read until the agent has the task past `SUBMITTED`, and close the
  stream; the stand-in then follows the task. A task still `WORKING` is followed even
  with `updates = "off"`. `self` gets the full brief (`lifecycle: delegated`, the parent's
  `model` and `reasoning_effort`, `parent_tasks`); another agent gets the name, goal,
  description and acceptance criteria (issue-34 R7.2, R7.3).
- WHEN a stand-in is cancelled by its parent THEN it SHALL cancel the child with
  `CancelTask` (issue-34 R7.6).
- A follow SHALL skip the history `SubscribeToTask` replays after its first snapshot (by
  the status timestamp), so a replayed state is never read as a change; every stream the
  harness opens on an agent SHALL be closed on every exit (issue-34).

## Design

[design.md § Agents, local and remote](../specs/issue-3/design.md#agents-local-and-remote-r11-r7--harnessagents),
[issue-27 design](../specs/issue-27/design.md),
[issue-34 design](../specs/issue-34/design.md).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | The agent entity, `RemoteAgent`, card validation, the remote task workflow (Layer 5) | [spec](../specs/issue-3/), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11) |
| issue-27 | Push and follow watches on a parked remote task; push config cleanup; the parent noted only of endings and new questions; `X-Participant-Id` on every remote task call (fixing replies to a parked tiny-harness peer) | [spec](../specs/issue-27/), [PR #28](https://github.com/MadaraUchiha-314/tiny-harness/pull/28) |
| issue-34 | The agents roster in the model's context; `spawn_subtask` refuses an unknown agent | [spec](../specs/issue-34/), [PR #35](https://github.com/MadaraUchiha-314/tiny-harness/pull/35) |
| issue-34 (R7) | The harness is the agent `self`; children are created with `start_agent_task` and cancelled with `CancelTask`; follows skip replayed history; streams are closed | [spec](../specs/issue-34/), [PR #35](https://github.com/MadaraUchiha-314/tiny-harness/pull/35) |
| issue-36 | Agents in the same service connected on first use (`RemoteAgent.deferred`) | [spec](../specs/issue-36/), [PR #37](https://github.com/MadaraUchiha-314/tiny-harness/pull/37), [decision-009](../decisions/decision-009.md) |
