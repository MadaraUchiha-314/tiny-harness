---
type: evidence
workItem: issue-20
---

# Documentation

Work item: issue-20 · tasks.md task 4 · testing-plan row T12.

## Capability docs

| Doc | What changed |
|---|---|
| [surfaces-and-renderers](../../../capabilities/surfaces-and-renderers.md) | The TUI asserts `--participant`, else the OS user name; exit 2 when neither yields an id; the composer shows the id; history row |
| [capabilities index](../../../capabilities/capabilities.md) | Unchanged. The one-line summary is still accurate. |

## Documentation

| Doc | What changed | Requirement |
|---|---|---|
| `README.md` | The TUI line in the quick start says it sends as the OS user and names `--participant` | R1.1, R1.3 |
| `docs/guide/getting-started.md` | "Run the demo": the TUI's default identity, `--participant`, and that the id is self-asserted | R1.1, R1.3 |

`docs/guide/deployment.md` and `docs/architecture/architecture.md` are unchanged: no
configuration key, service or component was added. No decision record was added. The
default-versus-require choice is local to this fix and recorded in `bugfix.md` and
`design.md`.
