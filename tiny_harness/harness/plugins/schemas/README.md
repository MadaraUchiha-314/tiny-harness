# Vendored Agent Plugins 1.0.0 schemas

`plugin.schema.json` and `mcp.schema.json` are the published schemas of the
[Agent Plugins specification](https://agent-plugins.org/) 1.0.0, fetched verbatim from
`https://agent-plugins.org/schemas/1.0.0/` on 2026-10-09. They are the normative check the
loader runs before its own typed models; the specification's loading rules (unknown
top-level fields are non-fatal, component failures skip the component) are implemented in
`loader.py`.
