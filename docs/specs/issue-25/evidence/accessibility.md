# Accessibility

Issue #25, verification run on 2026-10-12 against `loop/issue-25` at `2393e75`.
Testing-plan rows: T9.

## Web

`cd renderers/web && bun run test:a11y` (axe and keyboard reach, Playwright)

```text

  4 passed (20.5s)
rc=0 secs=36
```

- **axe:** no violations on the header controls or on the open command listbox (a
  WAI-ARIA combobox). The highlighted option's muted text uses the normal text colour,
  because axe measured its contrast at 4.34:1.
- **Keyboard:** Tab reaches Complete, Cancel, the listbox options, the sub-task link and
  ← Parent.

## TUI

`uv run pytest tests/ui/test_tui_keys.py` passes (part of T5). Every action has a key:

- `ctrl+d` complete
- `ctrl+c` cancel
- `f4` parent
- `f2` cycles the panes
- `/` completion

In the T11 walkthrough, Tab cycles four focus stops: the composer, the conversation, the
pane tabs and the sub-task list. On the sub-task list, Enter opens the highlighted
sub-task.
