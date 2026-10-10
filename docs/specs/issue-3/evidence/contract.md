# Contract and snapshot tests — T3, T6

Every public interface named in `design.md` has an API snapshot under
`tests/contract/snapshots/` (entities, hooks and contexts, registry, errors, plugins,
prompts, skills, models and tools, channels, persistence, configuration and the
`Settings` JSON schema); the agent card and the extension schemas under `docs/a2a/ext/`
(task, channel, the twelve intrinsic tools) are pinned by snapshot. A snapshot changes
only through `UPDATE_API_SNAPSHOTS=1` on purpose: Layer 9 recorded two new optional
settings (`temporal.search_attributes`, `o11y.trace_file`) that way.

```text
## uv run pytest tests/contract -q
.............................                                            [100%]
29 passed in 2.82s
```

```text
## uv run pytest tests/contract -q -k snapshot
..............                                                           [100%]
14 passed, 15 deselected in 2.82s
```
