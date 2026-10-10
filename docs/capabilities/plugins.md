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
  the manifest declares.
- WHEN a plugin is loaded THEN every skill, MCP server, hook and prompt it declares SHALL
  be registered; the plugin's manifest version is the entity version. A second
  registration of the same `(id, version)` SHALL be refused unless the loading order
  declares an override.
- The built-in plugin SHALL ship the default system prompt, the intrinsic tools and the
  default `in` bodies, loaded first and overridable through the same mechanism.

## Design

[design.md § Plugins](../specs/issue-3/design.md#plugins-r3--harnessplugins).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Manifest models, loader, registrar, namespace directory, built-in plugin (Layer 2); the demo plugin under `examples/demo` (Layer 9) | [spec](../specs/issue-3/), [PR #8](https://github.com/MadaraUchiha-314/tiny-harness/pull/8) |
