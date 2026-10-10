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
- `A2A-Extensions` SHALL name only extensions the remote card advertises.
- WHEN the harness delegates (`spawn_subtask` naming a remote agent) THEN a sub-task
  SHALL be created, linked to the remote A2A task id, and tracked through the remote
  task's status updates, including `INPUT_REQUIRED` and `AUTH_REQUIRED`; the child
  workflow signals the parent when it is done, and the parent SHALL NOT complete while a
  sub-task is unresolved.
- The harness itself SHALL be a `LocalAgent` with the same interface.

## Design

[design.md § Agents, local and remote](../specs/issue-3/design.md#agents-local-and-remote-r11-r7--harnessagents).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | The agent entity, `RemoteAgent`, card validation, the remote task workflow (Layer 5) | [spec](../specs/issue-3/), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11) |
