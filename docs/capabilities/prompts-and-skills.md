# Capability: prompts-and-skills

> A minimal system prompt stored as markdown that plugins replace or extend, and Agent
> Skills loaded with progressive disclosure through tool calls.

## What it is

The harness's voice and its procedural knowledge. The system prompt is a document, not a
string; a skill is a directory written to the Agent Skills specification, exposed to the
model by name and loaded in full only when it asks. Lives in
`tiny_harness/harness/prompts/` and `tiny_harness/harness/skills/`.

## Current behaviour

### System prompt

- The default system prompt SHALL be the built-in plugin's
  `io.github.madarauchiha-314.tiny-harness/systemprompt.md`, parsed into
  the sections `role`, `task`, `participants`, `tools`, `skills` and `rules` by its `##`
  headings.
- A plugin SHALL replace the whole prompt with a `systemprompt.md` in its namespace
  directory, or extend one section with a prompt file whose front matter says
  `extends: <section>`.
- WHEN the context window is assembled THEN the stable sections of the prompt SHALL be
  rendered first, at a fixed position in the cached prefix; the participants' roles are
  always included.

### Skills

- A skill SHALL be a directory named after its `name` field holding `SKILL.md` (YAML front
  matter with `name` and `description` required; `license`, `compatibility`, `metadata`,
  `allowed-tools` optional) and optional `scripts/`, `references/` and `assets/`, one
  level deep. The loader is the harness's own and validates the specification's rules
  (name pattern and length, description length, compatibility length, space-separated
  `allowed-tools`).
- WHEN a skill fails validation THEN it SHALL be skipped with the reason recorded and
  the others loaded.
- A skill SHALL be an entity addressed by `(id, version)`.
- The skills' names and descriptions SHALL be in the context window; a body SHALL be
  loaded only through `load_skill` and a resource only through `load_skill_resource`.
  The skill tools are `list_skills`, `load_skill`, `unload_skill`,
  `list_skill_resources` and `load_skill_resource`.
- WHEN a skill is loaded THEN the MCP servers an optional `mcp.json` inside the skill
  directory declares SHALL be connected and their tools registered, and the loaded body
  and tool definitions recorded in the agent state through the `skill_loaded` command;
  `unload_skill` reverses it. A loaded skill's body is in the never-compact set.

## Design

[design.md § System prompt](../specs/issue-3/design.md#system-prompt-r4--harnessprompts),
[design.md § Skills](../specs/issue-3/design.md#skills-r5--harnessskills).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Prompt entities, the markdown system prompt, the skills loader (Layer 2); the skill tools (Layer 3) | [spec](../specs/issue-3/), [PR #8](https://github.com/MadaraUchiha-314/tiny-harness/pull/8), [PR #9](https://github.com/MadaraUchiha-314/tiny-harness/pull/9) |
