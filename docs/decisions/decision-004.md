# Decision 004: Harness intrinsics are tools, so the core loop stays five lines

- **Status:** proposed (accepted when the issue-3 design is approved)
- **Date:** 2026-10-09
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #3](https://github.com/MadaraUchiha-314/tiny-harness/issues/3)

## Context

The ticket fixes the core loop as sherma's pseudo-code: create context, invoke the LLM,
extract tool calls, execute them, repeat until there are none. The requirements also ask
for plans, steps, sub-tasks, help requests, participant tasks and skill loading, each
hooked and overridable. Adding each as a branch of the loop would turn five lines into a
state machine nobody can hold in their head.

## Decision

Everything the harness can do beyond calling the LLM is a **tool in the registry**,
shipped by the built-in plugin: `create_plan`, `complete_step`, `spawn_subtask`,
`ask_participant`, `create_task_for_participant`, `load_skill`, `unload_skill`,
`list_skill_resources`, `load_skill_resource`, `emit_ui` (A2UI). The LLM calls them like
any MCP tool. Each is marked `execution: intrinsic`, so the loop dispatches it to the
workflow (a child workflow for a sub-task, a wait for a help request) instead of to an
activity that calls an MCP server.

## Consequences

- The loop is exactly the ticket's pseudo-code; behaviour grows by registering tools.
- Every intrinsic is overridable the same way as any default: replace the registry entry
  from a plugin, or wrap its invocation with a hook.
- The LLM sees one uniform tool surface, which keeps the tool-definition prefix stable
  for prompt caching.
- A tool call is the only way the LLM influences the harness, so the tool registry and
  schema validation are the single enforcement point for prompt injection.

## Alternatives considered

- **Special-casing plan and help in the loop** — more code paths, each needing its own
  hook and override story.
- **Structured output instead of tool calls for planning** — a second channel from the
  LLM into the harness, with a second validation path.
