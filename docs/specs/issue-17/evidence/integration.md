# Integration tests: embedded mode

Work item: issue-17 · testing-plan row T2 · commit `cdd0785` · run 2026-10-10 on Linux (Python 3.14, temporalio 1.34.0, Temporal CLI 1.9.1).

## The embedded scenarios against the real dev server

```sh
env -u TEMPORAL_API_KEY uv run pytest tests/integration/embedded -v --basetemp ~/.cache/tiny-harness-pytest/run 2>&1 | grep -E 'PASSED|FAILED|ERROR|SKIPPED|passed|failed'
```

Exit status `0` in 27.5 s.

````text
tests/integration/embedded/test_cli_embedded.py::test_tui_hosts_its_own_harness_in_embedded_mode PASSED [  6%]
tests/integration/embedded/test_cli_embedded.py::test_tui_with_a_url_starts_no_embedded_server PASSED [ 13%]
tests/integration/embedded/test_cli_embedded.py::test_admin_commands_act_on_persisted_embedded_state PASSED [ 20%]
tests/integration/embedded/test_cli_embedded.py::test_sigterm_to_serve_in_embedded_mode_leaves_no_dev_server PASSED [ 26%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_mode_starts_without_temporal_credentials PASSED [ 33%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_server_binds_loopback_only PASSED [ 40%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_server_stops_when_the_harness_exits[normal] PASSED [ 46%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_server_stops_when_the_harness_exits[exception] PASSED [ 53%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_server_stops_when_the_harness_exits[cancellation] PASSED [ 60%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_state_survives_a_restart PASSED [ 66%]
tests/integration/embedded/test_embedded_temporal.py::test_a_second_process_cannot_open_the_same_embedded_state PASSED [ 73%]
tests/integration/embedded/test_embedded_temporal.py::test_an_in_process_second_owner_is_refused_too PASSED [ 80%]
tests/integration/embedded/test_embedded_temporal.py::test_startup_time PASSED [ 86%]
tests/integration/embedded/test_running_harness.py::test_programmatic_harness_runs_a_task_in_embedded_mode PASSED [ 93%]
tests/integration/embedded/test_running_harness.py::test_embedded_server_registers_search_attributes_and_the_heartbeat_schedule PASSED [100%]
======================= 15 passed, 10 warnings in 23.22s =======================
````

## Scenario table

```sh
the-loop scenarios --root "$PWD" --glob 'tests/integration/embedded/*.py' --format markdown
```

Exit status `0` in 0.4 s.

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | Embedded Temporal mode | TUI hosts its own harness in embedded mode | docs/specs/issue-17/requirements.md#R5 | tests/integration/embedded/test_cli_embedded.py:68 |
| 2 | Embedded Temporal mode | TUI with a URL starts no embedded server | docs/specs/issue-17/requirements.md#R5 | tests/integration/embedded/test_cli_embedded.py:114 |
| 3 | Embedded Temporal mode | Admin commands act on persisted embedded state | docs/specs/issue-17/requirements.md#R5 | tests/integration/embedded/test_cli_embedded.py:143 |
| 4 | Embedded Temporal mode | Embedded server stops when serve receives SIGTERM | docs/specs/issue-17/requirements.md#R2 | tests/integration/embedded/test_cli_embedded.py:177 |
| 5 | Embedded Temporal mode | Embedded mode starts without Temporal credentials | docs/specs/issue-17/requirements.md#R1 | tests/integration/embedded/test_embedded_temporal.py:149 |
| 6 | Embedded Temporal mode | Embedded server binds loopback only | docs/specs/issue-17/requirements.md#R2 | tests/integration/embedded/test_embedded_temporal.py:167 |
| 7 | Embedded Temporal mode | Embedded server stops when the harness exits | docs/specs/issue-17/requirements.md#R2 | tests/integration/embedded/test_embedded_temporal.py:197 |
| 8 | Embedded Temporal mode | Embedded state survives a restart | docs/specs/issue-17/requirements.md#R3 | tests/integration/embedded/test_embedded_temporal.py:230 |
| 9 | Embedded Temporal mode | A second process cannot open the same embedded state | docs/specs/issue-17/design.md#security-design | tests/integration/embedded/test_embedded_temporal.py:263 |
| 10 | Embedded Temporal mode | Programmatic harness runs a task in embedded mode | docs/specs/issue-17/requirements.md#R6 | tests/integration/embedded/test_running_harness.py:71 |
| 11 | Embedded Temporal mode | Embedded server registers search attributes and the heartbeat schedule | docs/specs/issue-17/requirements.md#R2 | tests/integration/embedded/test_running_harness.py:97 |
