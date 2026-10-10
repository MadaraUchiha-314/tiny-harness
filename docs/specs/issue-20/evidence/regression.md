---
type: evidence
workItem: issue-20
---

# Regression

Work item: issue-20 · testing-plan rows T6, T8, T12 · run 2026-10-10 on Linux (Python 3.14).

## T6: TUI snapshots

```sh
uv run pytest tests/ui -q
```

Exit status `0` in 0.0 s.

```text
--------------------------- snapshot report summary ----------------------------
4 snapshots passed.
9 passed in 8.97s
```

The four snapshots were regenerated (`--snapshot-update`). Their rendered text, compared
line by line against `main`, differs only in the composer:

```text
test_conversation_state.raw 2
-▊Enter to send▎
+▊Enter to send as you▎
test_empty_state.raw 2
-▊Enter to send▎
+▊Enter to send as you▎
test_plan_pane.raw 2
-▊Enter to send▎
+▊Enter to send as you▎
test_trace_pane.raw 2
-▊Enter to send▎
+▊Enter to send as you▎
```

A first draft put the participant in the top bar instead. The same comparison showed it
pushing `INPUT_REQUIRED` off the right edge at 110 columns, so it moved to the composer
(design.md § UI/UX design).

## T8: abuse cases still hold

```sh
uv run pytest tests/security tests/integration/a2a -q --basetemp ~/.cache/tiny-harness-pytest/i20s
```

Exit status `0` in 0.0 s.

```text
33 passed, 106 warnings in 32.20s
```

The server's `no participant asserted` refusal (abuse case 1) and the task-access checks
against an asserted id (abuse case 2) pass unchanged; this PR does not touch
`tiny_harness/service/a2a/`.

## T12: pre-commit on every file (CI's lint job)

```sh
uv run pre-commit run --all-files
```

Exit status `0` in 0.0 s.

```text
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
```

## T12: CI's test commands

```sh
uv run pytest tests/integration tests/contract tests/security tests/ui -q --basetemp ~/.cache/tiny-harness-pytest/i20ci
```

First run: exit status `1` in 88.3 s. One failure, in a test
this PR does not touch:

```text
FAILED tests/integration/o11y/test_observability.py::test_one_span_per_operation_with_genai_attributes_crosses_the_workflow_boundary
E       assert 1 == 0
E        +  where 1 = <tiny_harness.service.o11y.hook.O11yExecutor object at 0x…>.open_spans
1 failed, 113 passed, 354 warnings in 86.60s (0:01:26)
```

The test passed 3 of 3 times on its own. Neither `tiny_harness/service/o11y` nor
`tests/integration/o11y` differs from `main`. It reads as a timing race on span close
under full-suite load, so it is a pre-existing flake, reported on the PR rather than
fixed here. Second run of the same command: exit status `0` in 85.4 s.

```text
4 snapshots passed.
114 passed, 349 warnings in 83.71s (0:01:23)
```
