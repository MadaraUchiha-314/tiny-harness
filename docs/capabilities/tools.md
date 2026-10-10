# Capability: tools

> Tools come from MCP servers and from the harness's own intrinsics; the model reaches a
> tool only through a validated call to a registered name.

## What it is

The only way text becomes an action. An MCP server's tools become entities; the
harness's own operations (plans, sub-tasks, help requests, participants, skills, UI) are
intrinsic tools that return a command the workflow applies. Lives in
`tiny_harness/harness/tools/`.

## Current behaviour

- The system SHALL connect to MCP servers with the official `mcp` SDK over stdio and
  streamable HTTP, list their tools and register each as a tool entity named
  `<plugin>/<server>.<tool>` with its input schema.
- A tool's idempotency SHALL come from the server's annotations (`idempotent_hint` or
  `read_only_hint`); an MCP tool with neither is not idempotent and is never retried
  automatically.
- WHEN the model names a tool that is not in the registry THEN nothing SHALL run and a
  typed error SHALL be the tool result. WHEN the arguments fail the input schema THEN the
  tool SHALL NOT be invoked and the validation error SHALL be the tool result.
- Every tool result SHALL be marked untrusted and rendered in the context window as data
  inside a delimited block, never as instructions.
- An MCP tool's input schema SHALL be hashed at registration; before the first call to
  any of a server's tools in a loop iteration the source re-lists once, and a changed
  tool refuses every call with `ToolSchemaChangedError` until it is re-registered.
- No tool SHALL be present by default; file system, shell and network tools exist only
  when a plugin registers them.
- The intrinsic tools SHALL be `create_plan`, `complete_step`, `spawn_subtask`,
  `ask_participant`, `create_task_for_participant`, `set_participant_role`,
  `list_skills`, `load_skill`, `unload_skill`, `list_skill_resources`,
  `load_skill_resource` and `emit_ui`. An intrinsic returns a `WorkflowCommand` the
  workflow applies deterministically; the model reads the command's result next turn.
  Their JSON schemas are committed under `docs/a2a/ext/intrinsics/` and pinned by a
  contract test.
- Tool names SHALL cross the provider boundary as names the provider accepts
  (`[A-Za-z0-9_-]`, at most 64 characters): each adapter builds a per-request bijection,
  encodes names on the way out and decodes them on the tool calls that come back.

## Design

[design.md § Tools and MCP](../specs/issue-3/design.md#tools-and-mcp-r6--harnesstools),
[decision-004](../decisions/decision-004.md).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Tool models, the validating invoker, the MCP tool source, intrinsic definitions (Layer 3); intrinsic bodies (Layer 4); provider-safe wire names (Layer 9) | [spec](../specs/issue-3/), [PR #9](https://github.com/MadaraUchiha-314/tiny-harness/pull/9), [PR #10](https://github.com/MadaraUchiha-314/tiny-harness/pull/10) |
