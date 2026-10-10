---
type: evidence
workItem: issue-20
---

# Unit tests

Work item: issue-20 · testing-plan row T1 · commit `38637b4`, run 2026-10-10 on
Linux (Python 3.14).

## Red: before the implementation

The new tests in `tests/unit/service/test_cli.py` import `tui_participant`, which did
not exist yet:

```sh
uv run pytest tests/unit/service/test_cli.py -q
```

```text
ERROR tests/unit/service/test_cli.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.23s
```

## Green: the unit suite

```sh
uv run pytest tests/unit -q
```

Exit status `0` in 5.3 s (re-run at commit `38637b4`).

```text
260 passed in 3.83s
```

The issue-20 cases, run on their own (`uv run pytest tests/unit/service/test_cli.py -v -k "participant"`):

```text
tests/unit/service/test_cli.py::test_tui_parses_a_participant PASSED
tests/unit/service/test_cli.py::test_tui_participant_is_the_flag_else_the_os_user PASSED
tests/unit/service/test_cli.py::test_tui_participant_is_none_when_nothing_can_be_asserted PASSED
tests/unit/service/test_cli.py::test_tui_participant_refuses_what_the_header_cannot_carry[jos\xe9] PASSED
tests/unit/service/test_cli.py::test_tui_participant_refuses_what_the_header_cannot_carry[a\nb] PASSED
tests/unit/service/test_cli.py::test_tui_participant_refuses_what_the_header_cannot_carry[a\rb] PASSED
tests/unit/service/test_cli.py::test_tui_participant_refuses_what_the_header_cannot_carry[\u540d\u524d] PASSED
tests/unit/service/test_cli.py::test_tui_participant_refuses_what_the_header_cannot_carry[tab\there] PASSED
tests/unit/service/test_cli.py::test_tui_without_a_participant_exits_two_before_connecting[flag0] PASSED
tests/unit/service/test_cli.py::test_tui_without_a_participant_exits_two_before_connecting[flag1] PASSED
tests/unit/service/test_cli.py::test_tui_without_a_participant_exits_two_before_connecting[flag2] PASSED
tests/unit/service/test_cli.py::test_tui_without_a_participant_exits_two_before_connecting[flag3] PASSED
tests/unit/service/test_cli.py::test_tui_passes_the_resolved_participant_to_the_command PASSED
tests/unit/service/test_cli.py::test_tui_command_hands_the_participant_to_run_tui PASSED
```
