---
type: evidence
workItem: issue-20
---

# Integration tests

Work item: issue-20 · testing-plan rows T2 and T5 · commit `b932be3` (code), run
2026-10-10 on Linux (Python 3.14, temporalio 1.34.0, textual 8.2.8).

## Red: the bug, reproduced through the real `run_tui` path

The regression scenario *TUI sends a message under the asserted participant* was run on
the unfixed code, calling `commands.tui(settings, url=None)` because the old signature
takes no participant. The real `run_tui` → `SdkClient.connect` → `HarnessApp` path
sent the message and the server refused it, which is the ticket's symptom:

```text
>       assert await commands.tui(settings, url=None) == 0
E                   textual.worker.WorkerFailed: Worker raised exception: InvalidParamsError('no participant asserted')
```

## Green: the embedded integration suite

```sh
uv run pytest tests/integration/embedded -v --basetemp ~/.cache/tiny-harness-pytest/i20
```

Exit status `0` in 0.0 s.

```text
tests/integration/embedded/test_cli_embedded.py::test_tui_hosts_its_own_harness_in_embedded_mode PASSED
tests/integration/embedded/test_cli_embedded.py::test_tui_sends_a_message_under_the_asserted_participant PASSED
tests/integration/embedded/test_cli_embedded.py::test_tui_with_a_url_starts_no_embedded_server PASSED
tests/integration/embedded/test_cli_embedded.py::test_admin_commands_act_on_persisted_embedded_state PASSED
tests/integration/embedded/test_cli_embedded.py::test_sigterm_to_serve_in_embedded_mode_leaves_no_dev_server PASSED
tests/integration/embedded/test_cli_embedded.py::test_sigterm_to_programmatic_serve_leaves_no_dev_server PASSED
======================= 17 passed, 15 warnings in 29.59s =======================
```

- *TUI sends a message under the asserted participant* (R1.2, R1.6, R1.7, R2.1) runs
  the real `run_tui`. Only `HarnessApp.run_async` is replaced, by Textual's pilot. It
  reaches `COMPLETED` and reads `Enter to send as alice` from the composer (T5).
- *TUI hosts its own harness in embedded mode* (R2.2) now takes `participant` from the
  command instead of choosing `alice` itself.

## Scenarios covered

`the-loop scenarios --root "$PWD" --glob 'tests/integration/embedded/*.py' --format markdown` (TUI rows):

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | Embedded Temporal mode | TUI hosts its own harness in embedded mode | docs/specs/issue-17/requirements.md#R5 | tests/integration/embedded/test_cli_embedded.py:72 |
| 2 | TUI participant assertion | TUI sends a message under the asserted participant | docs/specs/issue-20/bugfix.md#R1 | tests/integration/embedded/test_cli_embedded.py:128 |
| 3 | Embedded Temporal mode | TUI with a URL starts no embedded server | docs/specs/issue-17/requirements.md#R5 | tests/integration/embedded/test_cli_embedded.py:166 |
