# Capability: hooks

> A `pre`, `in` and `post` hook point on every operation the harness performs, run as an
> ordered chain of typed executors, local or remote.

## What it is

The extension mechanism everything else is built on: observability, retries, policy,
compaction and the harness's own default behaviours are hook executors, not core code.
Every operation runs through the hook-wrapped operation runner, which is also the body of
every Temporal activity. Lives in `tiny_harness/harness/hooks/`.

## Current behaviour

- The catalogue SHALL be the operations `request.received`, `task.created`,
  `task.state_changed`, `task.complete`, `context.created`, `llm.invoked`,
  `tool_calls.extracted`, `tool.invoked`, `system_one.invoked`, `plan.created`,
  `step.started`, `step.finished`, `subtask.spawned`, `help.requested`, `help.decided`,
  `channel.sent`, `channel.received`, `compaction.trigger`, `compaction.keep`,
  `compaction.summarise`, `persistence.read`, `persistence.write`, `activity.failed`,
  `activity.retried`, `heartbeat.tick`, `shutdown`, `skill.loaded`, `skill.unloaded` and
  `agent.invoked`,
  each with the phases `pre`, `in` and `post`; the hook point name is
  `<operation>.<phase>`.
- Executors for one hook point SHALL run as an ordered chain by priority, each receiving
  the typed context the previous one returned and returning a replacement or `None` to
  pass through.
- WHEN a `pre` executor returns a replacement THEN the operation SHALL use it as its
  input; a `pre` executor on `tool.invoked` can veto or rewrite one tool call. WHEN a
  `post` executor returns a replacement THEN it SHALL be the operation's output.
- The `in` phase SHALL be the operation's body: the built-in plugin registers each
  default body at priority 1000, and an executor with a lower priority that sets the
  context's `result` replaces it.
- WHEN an executor raises a typed abort THEN the operation SHALL be cancelled, the abort
  recorded, and surfaced as a task failure or a refusal, never as an unhandled exception.
- Every context SHALL carry the task reference, the participants, the entity references,
  the correlation id and the attempt number.
- The redactor SHALL scrub the context before any executor sees it and the output before
  it is returned.
- Remote executors SHALL be supported over JSON-RPC 2.0 (method = the hook point, params
  `{"context": …}`) and over MCP (tool `hooks.<operation>.<phase>`); any transport failure
  or non-conforming reply SHALL raise `HookTransportError`, so the operation fails through
  the retry path and `activity.failed` runs. Nothing passes through silently.
- Hooks SHALL never run in workflow code: the activity wrapper runs the chain around each
  activity's body, and the workflow runs `activity.failed` and `activity.retried` through
  the `dispatch_hooks` activity between attempts.
- The async HTTP client, the clock and the random source SHALL be provider objects given
  to the harness at construction; workflow code uses Temporal's `workflow.now()` and
  `workflow.random()`.

## Design

[design.md § Hooks](../specs/issue-3/design.md#hooks-r2--harnesshooks),
[decision-004](../decisions/decision-004.md).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Hook points, contexts, executor chain, remote executors, providers (Layer 1); the operation runner (Layer 4); the activity wrapper and workflow-managed retries (Layer 5) | [spec](../specs/issue-3/), [PR #7](https://github.com/MadaraUchiha-314/tiny-harness/pull/7), [PR #10](https://github.com/MadaraUchiha-314/tiny-harness/pull/10), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11) |
