# Capability: plugins

> Skills, MCP servers, hooks and prompts reach a deployment as Agent Plugins, from a
> directory or from code, with the built-in defaults as the first plugin.

## What it is

The one way to extend a deployment without a fork. The loader reads a plugin
directory, validates it, contains its paths, expands its variables and registers every
component through the registrar. Lives in `tiny_harness/harness/plugins/`; the defaults
in `tiny_harness/builtin/`.

## Current behaviour

- The system SHALL load plugins conforming to Agent Plugins 1.0.0: a directory with
  `plugin.json`, optional `skills/<name>/SKILL.md` and optional `mcp.json`, validated
  against the published schemas. The same `Plugin` model built in code is the
  programmatic form.
- Hooks and prompts SHALL be read from the plugin's client-specific directory
  `io.github.madarauchiha-314.tiny-harness/` (`hooks.json`, `prompts/*.md`,
  `systemprompt.md`); other clients' namespaced directories SHALL be ignored.
- WHEN `plugin.json` fails its schema THEN the whole plugin SHALL be rejected with a
  `PluginError` naming the manifest path and nothing of it loaded. WHEN one component of
  a valid plugin fails THEN that component SHALL be skipped with its reason recorded in
  the load report and the rest loaded. Component types the harness does not support
  (legacy SSE servers) are skipped the same way.
- WHEN a component path or an MCP `cwd` resolves outside the plugin root (or outside the
  plugin's data directory for `${PLUGIN_DATA}`) THEN that component SHALL be rejected.
- Only `${PLUGIN_ROOT}` and `${PLUGIN_DATA}` SHALL expand, in `args`, `env` values and
  `cwd`, never in `command`; both SHALL be passed as environment variables to MCP
  subprocesses, which receive nothing else of the parent environment beyond the `env`
  the manifest declares and the MCP SDK's minimal defaults (`HOME`, `PATH`, `USER`,
  `SHELL`, `TERM`, `LOGNAME`).
- WHEN a plugin is loaded THEN every skill, MCP server, hook and prompt it declares SHALL
  be registered; the plugin's manifest version is the entity version. A second
  registration of the same `(id, version)` SHALL be refused unless the loading order
  declares an override.
- A plugin SHALL be able to declare slash commands in its namespace directory's
  `commands.json` (`{"commands": [{name, description, argument_hint, hook}]}`, schema
  [`docs/plugins/commands.json`](https://github.com/MadaraUchiha-314/tiny-harness/blob/main/docs/plugins/commands.json)),
  each body the `HookDef` named by `hook` in its `hooks.json`, local or remote. That
  hook is command-owned: it SHALL declare exactly `points: ["command.invoked.in"]`, is
  registered only as that command's filtered body and never as an ordinary hook (even
  when the command is skipped), and no two commands may own it. An invalid name, a name
  already registered without override, a missing `HookDef`, other points or a shared
  hook SHALL skip the command with a `command` entry in the load report. Without a
  command registry, a plugin's commands are skipped.
- A plugin loaded with override SHALL replace an earlier command's spec and disable its
  earlier body entirely, whatever the priorities. `pre` and `post` executors on
  `command.invoked` are ordinary `HookDef`s and see every command.
- The built-in plugin SHALL ship the default system prompt, the intrinsic tools and the
  default `in` bodies, loaded first and overridable through the same mechanism. The
  built-in commands `/model`, `/effort`, `/sub-task`, `/status` and `/exit` come from code
  (`harness/commands/builtins.py`) at the default body priority, with the role policy
  registered whenever there is a command registry; `builtin_commands=False` leaves the
  five out.

## Design

[design.md § Plugins](../specs/issue-3/design.md#plugins-r3--harnessplugins).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Manifest models, loader, registrar, namespace directory, built-in plugin (Layer 2); the demo plugin under `examples/demo` (Layer 9) | [spec](../specs/issue-3/), [PR #8](https://github.com/MadaraUchiha-314/tiny-harness/pull/8) |
| issue-25 | `commands.json` with command-owned hooks, command override, the four built-in commands | [spec](../specs/issue-25/), [PR #26](https://github.com/MadaraUchiha-314/tiny-harness/pull/26), [decision-007](../decisions/decision-007.md) |
