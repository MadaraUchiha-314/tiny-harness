# Web renderer: visual and accessibility runs — T5, T9

Playwright's own Chromium (Chrome for Testing 156, `bun x playwright install chromium`),
as CI uses. The system Chromium 152 crashes its renderer on the shadcn page under
Playwright's launch flags while rendering the same page fine on its own, so
`TINY_HARNESS_CHROMIUM` is no longer used for these runs. The visual project compares the prototype state (light, dark, phone)
and the plan tab against the committed baselines only when `TINY_HARNESS_VISUAL_STRICT=1`;
otherwise it writes the screenshots for review. The a11y project runs axe-core with the
`wcag2a` and `wcag2aa` tags on the `INPUT_REQUIRED` state and walks every control with
the keyboard.

## `bun run --cwd renderers/web test:visual`

```text
Running 4 tests using 1 worker

  ✓  1 [visual] › e2e/visual.spec.ts:26:3 › prototype state renders (light) (676ms)
  ✓  2 [visual] › e2e/visual.spec.ts:26:3 › prototype state renders (dark) (801ms)
  ✓  3 [visual] › e2e/visual.spec.ts:26:3 › prototype state renders (phone) (536ms)
  ✓  4 [visual] › e2e/visual.spec.ts:41:1 › the plan tab shows the DAG (587ms)

  4 passed (4.0s)
```

## `bun run --cwd renderers/web test:a11y`

```text
Running 2 tests using 1 worker

  ✓  1 [a11y] › e2e/a11y.spec.ts:4:1 › the prototype state has no axe violations (1.2s)
  ✓  2 [a11y] › e2e/a11y.spec.ts:11:1 › every control is reachable by keyboard (671ms)

  2 passed (3.1s)
```

axe violations: none (`results.violations` is `[]`). Keyboard walk: the Cancel button,
the composer textarea, the Task/Plan/Trace tabs, the A2UI card's picker and button and
the Send button are all reached by Tab; Enter on the Plan tab opens its panel.

## TUI snapshots and keys (`uv run pytest tests/ui -q`)

```text
## uv run pytest tests/ui -q
.........                                                                [100%]
--------------------------- snapshot report summary ----------------------------
4 snapshots passed.
9 passed in 9.22s
```

```text
## uv run pytest tests/ui -q -k keys
....                                                                     [100%]
4 passed, 5 deselected in 6.17s
```

## Live captures of the demo (this directory)

Taken against the running demo (`python -m examples.demo`, Temporal Cloud, `gpt-6.1-sol`)
by `renderers/web/scripts/capture-demo.ts` (Playwright; the text reply is sent from a
second renderer attached with `?task=`, and the first renderer reaches `COMPLETED`
through its subscription: `web-second-surface.png`) and a Textual pilot script
(`HarnessApp.run_test` with `SdkClient`, screenshots via `save_screenshot`, rasterised by
`renderers/web/scripts/svg-to-png.ts`). One task per surface; the two surfaces were
captured one after the other on the same instance.

| State | Web | TUI |
|---|---|---|
| empty | `web-empty.png` | `tui-empty.png` |
| WORKING | `web-working.png` | `tui-working.png` |
| A2UI card rendered (basic catalog: Card, Column, Text, ChoicePicker, Button) | `web-card.png` | `tui-card.png` |
| INPUT_REQUIRED with the help request | `web-input-required.png` | `tui-input-required.png` |
| the card's Confirm action sent | `web-action-sent.png` | `tui-action-sent.png` |
| COMPLETED with the summary | `web-completed.png` | `tui-completed.png` |
| the whole multi-turn flow | `web-multi-turn.gif` | `tui-multi-turn.gif` |
