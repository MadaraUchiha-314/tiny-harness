# Security / abuse-case tests

Work item: issue-17 · testing-plan row T8 · commit `cdd0785` · run 2026-10-10 on Linux (Python 3.14, temporalio 1.34.0, Temporal CLI 1.9.1).

## Abuse case → mechanism → test → result

Every row of design.md § Security design, the test that proves it, and its result in the
runs below. Tests outside `-k embedded` are named and run in the second section.

| Abuse case | Mechanism | Test | Result |
|---|---|---|---|
| 1 a network peer connects | `ip="127.0.0.1"` literal | `test_embedded_server_binds_loopback_only` — refused on the host's network address, **and every port the dev server listens on (frontend, metrics, internal services) is 127.0.0.1** | pass |
| 2 embedded + `address` / `tls` / `TEMPORAL_API_KEY` | validator, `load_settings` | `test_embedded_refuses_the_api_key`, `test_embedded_refuses_remote_only_keys[address]`, `[tls]`, `test_embedded_api_key_is_a_config_error` (CLI exit 2, key value not echoed) | pass |
| 3 absent or misspelled mode | `Literal` + default `remote` | `test_absent_mode_is_remote_and_unchanged`, `test_misspelled_mode_is_reported_before_the_missing_key` | pass |
| 4 bad `binary_path` | `os.access(X_OK)` | `test_binary_path_must_exist`, `test_binary_path_must_be_executable` | pass |
| 5 start failure | `EmbeddedTemporalError`, no fallback | `test_start_failure_is_wrapped_and_releases_the_lock` (remote `connect` stubbed to fail the test if called), `test_embedded_start_failure_exits_one_with_the_cause` | pass |
| 6 exit leaves no server | `finally`; SIGTERM cancels the main task | `test_embedded_server_stops_when_the_harness_exits[normal/exception/cancellation]`, `test_sigterm_to_serve_in_embedded_mode_leaves_no_dev_server`, `test_sigterm_cancels_the_command_so_its_cleanup_runs` | pass |
| 7 database permissions | `chmod 0600` before and after start | `test_a_new_database_is_owner_only`, `test_database_and_lock_are_owner_only`, and the real server's `-wal`/`-shm` in `test_embedded_state_survives_a_restart` | pass |
| 8 warning visible | log call | `test_logs_the_start_the_warning_and_the_download`; the e2e and T11 logs | pass |
| design: temp-dir binary plant | private `0700` download dir; group/other-writable refused | `test_default_download_dir_is_private_and_not_in_tmp`, `test_download_dir_is_created_owner_only`, `test_a_download_dir_others_can_write_is_refused` | pass |
| design: two owners, one database | `flock` on `<db>.lock` | `test_a_second_process_cannot_open_the_same_embedded_state` (a real second process), `test_a_second_owner_of_the_same_state_is_refused` | pass |

## Every test selected by -k embedded

```sh
env -u TEMPORAL_API_KEY uv run pytest tests/unit tests/integration/embedded tests/security -k embedded -v --basetemp ~/.cache/tiny-harness-pytest/run 2>&1 | grep -E 'PASSED|FAILED|ERROR|passed|failed'
```

Exit status `0` in 26.3 s.

````text
tests/unit/service/test_cli.py::test_worker_is_refused_in_embedded_mode PASSED [  2%]
tests/unit/service/test_cli.py::test_embedded_api_key_is_a_config_error PASSED [  5%]
tests/unit/service/test_cli.py::test_embedded_start_failure_exits_one_with_the_cause PASSED [  8%]
tests/unit/service/test_embedded_temporal.py::test_starts_on_loopback_with_the_persisted_database PASSED [ 10%]
tests/unit/service/test_embedded_temporal.py::test_in_memory_passes_no_database_and_takes_no_lock PASSED [ 13%]
tests/unit/service/test_embedded_temporal.py::test_binary_path_is_passed_through PASSED [ 16%]
tests/unit/service/test_embedded_temporal.py::test_a_new_database_is_owner_only PASSED [ 18%]
tests/unit/service/test_embedded_temporal.py::test_database_and_lock_are_owner_only PASSED [ 21%]
tests/unit/service/test_embedded_temporal.py::test_a_second_owner_of_the_same_state_is_refused PASSED [ 24%]
tests/unit/service/test_embedded_temporal.py::test_start_failure_is_wrapped_and_releases_the_lock PASSED [ 27%]
tests/unit/service/test_embedded_temporal.py::test_logs_the_start_the_warning_and_the_download PASSED [ 29%]
tests/unit/service/test_embedded_temporal.py::test_no_download_notice_when_the_binary_is_cached PASSED [ 32%]
tests/unit/service/test_embedded_temporal.py::test_default_download_dir_is_private_and_not_in_tmp PASSED [ 35%]
tests/unit/service/test_embedded_temporal.py::test_download_dir_is_created_owner_only PASSED [ 37%]
tests/unit/service/test_embedded_temporal.py::test_a_download_dir_others_can_write_is_refused PASSED [ 40%]
tests/unit/test_config_temporal_mode.py::test_remote_refuses_the_embedded_table PASSED [ 43%]
tests/unit/test_config_temporal_mode.py::test_embedded_loads_without_address_or_key PASSED [ 45%]
tests/unit/test_config_temporal_mode.py::test_embedded_keeps_namespace_and_task_queue PASSED [ 48%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_the_api_key PASSED [ 51%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_remote_only_keys[address = "localhost:7233"-temporal.address] PASSED [ 54%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_remote_only_keys[tls = true-temporal.tls] PASSED [ 56%]
tests/unit/test_config_temporal_mode.py::test_the_demo_embedded_config_loads_without_a_temporal_key PASSED [ 59%]
tests/integration/embedded/test_cli_embedded.py::test_tui_hosts_its_own_harness_in_embedded_mode PASSED [ 62%]
tests/integration/embedded/test_cli_embedded.py::test_tui_with_a_url_starts_no_embedded_server PASSED [ 64%]
tests/integration/embedded/test_cli_embedded.py::test_admin_commands_act_on_persisted_embedded_state PASSED [ 67%]
tests/integration/embedded/test_cli_embedded.py::test_sigterm_to_serve_in_embedded_mode_leaves_no_dev_server PASSED [ 70%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_mode_starts_without_temporal_credentials PASSED [ 72%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_server_binds_loopback_only PASSED [ 75%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_server_stops_when_the_harness_exits[normal] PASSED [ 78%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_server_stops_when_the_harness_exits[exception] PASSED [ 81%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_server_stops_when_the_harness_exits[cancellation] PASSED [ 83%]
tests/integration/embedded/test_embedded_temporal.py::test_embedded_state_survives_a_restart PASSED [ 86%]
tests/integration/embedded/test_embedded_temporal.py::test_a_second_process_cannot_open_the_same_embedded_state PASSED [ 89%]
tests/integration/embedded/test_embedded_temporal.py::test_an_in_process_second_owner_is_refused_too PASSED [ 91%]
tests/integration/embedded/test_embedded_temporal.py::test_startup_time PASSED [ 94%]
tests/integration/embedded/test_running_harness.py::test_programmatic_harness_runs_a_task_in_embedded_mode PASSED [ 97%]
tests/integration/embedded/test_running_harness.py::test_embedded_server_registers_search_attributes_and_the_heartbeat_schedule PASSED [100%]
=============== 37 passed, 239 deselected, 10 warnings in 22.18s ===============
````

## The config abuse cases (selected by name, outside -k embedded)

```sh
env -u TEMPORAL_API_KEY uv run pytest tests/unit/test_config_temporal_mode.py tests/unit/service/test_cli.py -v 2>&1 | grep -E 'refuse|misspelled|binary_path|api_key|PASSED.*(sigterm|start_failure)|passed|failed'
```

Exit status `0` in 4.1 s.

````text
tests/unit/test_config_temporal_mode.py::test_remote_still_requires_the_api_key PASSED [  7%]
tests/unit/test_config_temporal_mode.py::test_remote_refuses_the_embedded_table PASSED [ 18%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_the_api_key PASSED [ 29%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_remote_only_keys[address = "localhost:7233"-temporal.address] PASSED [ 33%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_remote_only_keys[tls = true-temporal.tls] PASSED [ 37%]
tests/unit/test_config_temporal_mode.py::test_misspelled_mode_is_reported_before_the_missing_key PASSED [ 40%]
tests/unit/test_config_temporal_mode.py::test_binary_path_must_exist PASSED [ 55%]
tests/unit/test_config_temporal_mode.py::test_binary_path_must_be_executable PASSED [ 59%]
tests/unit/test_config_temporal_mode.py::test_executable_binary_path_is_accepted PASSED [ 62%]
tests/unit/service/test_cli.py::test_worker_is_refused_in_embedded_mode PASSED [ 81%]
tests/unit/service/test_cli.py::test_admin_commands_are_refused_on_in_memory_state[command0] PASSED [ 85%]
tests/unit/service/test_cli.py::test_admin_commands_are_refused_on_in_memory_state[command1] PASSED [ 88%]
tests/unit/service/test_cli.py::test_embedded_api_key_is_a_config_error PASSED [ 92%]
============================== 27 passed in 2.76s ==============================
````
