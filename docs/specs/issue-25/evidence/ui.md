# UI and snapshot verification

Issue #25, verification run on 2026-10-12 against `loop/issue-25` at `2393e75`.
Testing-plan rows: T5, T6.

## TUI

`uv run pytest tests/ui`

```text
9 snapshots passed.
27 passed in 34.01s
rc=0 secs=37
```

These are the SVG snapshots of the new states, from the committed snapshot tests:

- `input-required-with-sub-state`: ![input-required-with-sub-state](ui/tui-input-required-with-sub-state.svg)
- `slash-completion-and-hint`: ![slash-completion-and-hint](ui/tui-slash-completion-and-hint.svg)
- `sub-task-row`: ![sub-task-row](ui/tui-sub-task-row.svg)
- `sub-task-open`: ![sub-task-open](ui/tui-sub-task-open.svg)
- `completed-state`: ![completed-state](ui/tui-completed-state.svg)

## Web

`cd renderers/web && bun run test:visual` (Playwright, system Chromium via
`TINY_HARNESS_CHROMIUM`)

```text

  12 passed (23.4s)
rc=0 secs=36
```

- `controls-light`: ![controls-light](ui/web-controls-light.png)
- `controls-dark`: ![controls-dark](ui/web-controls-dark.png)
- `controls-phone`: ![controls-phone](ui/web-controls-phone.png)
- `listbox`: ![listbox](ui/web-listbox.png)
- `sub-task-created`: ![sub-task-created](ui/web-sub-task-created.png)
- `sub-task-open`: ![sub-task-open](ui/web-sub-task-open.png)
- `completed-light`: ![completed-light](ui/web-completed-light.png)
- `completed-dark`: ![completed-dark](ui/web-completed-dark.png)
- `completed-phone`: ![completed-phone](ui/web-completed-phone.png)

The flow goes: reply → `/` listbox → `/sub-task` → open it → Complete the sub-task →
← Parent → Complete.

![flow](ui/web-task-controls-flow.gif)

The screens match the locked prototypes in `docs/specs/issue-25/design/`, except where
`design.md` changed during implementation:

- Web sub-task rows show the id and the agent, not "state · goal": showing state and goal
  would cost an extra request per sub-task.
- In the TUI, the reply is drawn before its state line.
