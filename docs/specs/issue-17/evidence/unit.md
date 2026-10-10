# Unit tests

Work item: issue-17 · testing-plan row T1 · commit `cdd0785` · run 2026-10-10 on Linux (Python 3.14, temporalio 1.34.0, Temporal CLI 1.9.1).

## The unit suite with no Temporal key

```sh
env -u TEMPORAL_API_KEY uv run pytest tests/unit -q
```

Exit status `0` in 5.5 s.

````text
........................................................................ [ 30%]
........................................................................ [ 60%]
........................................................................ [ 91%]
.....................                                                    [100%]
237 passed in 3.95s
````

## The issue-17 unit tests, by name

```sh
env -u TEMPORAL_API_KEY uv run pytest tests/unit/test_config_temporal_mode.py tests/unit/service/test_embedded_temporal.py tests/unit/service/test_cli.py -v -p no:randomly 2>&1 | grep -E 'PASSED|FAILED|ERROR|passed|failed'
```

Exit status `0` in 4.2 s.

````text
tests/unit/test_config_temporal_mode.py::test_absent_mode_is_remote_and_unchanged PASSED [  2%]
tests/unit/test_config_temporal_mode.py::test_remote_still_requires_the_api_key PASSED [  5%]
tests/unit/test_config_temporal_mode.py::test_remote_requires_address_and_namespace[address] PASSED [  7%]
tests/unit/test_config_temporal_mode.py::test_remote_requires_address_and_namespace[namespace] PASSED [ 10%]
tests/unit/test_config_temporal_mode.py::test_remote_refuses_the_embedded_table PASSED [ 12%]
tests/unit/test_config_temporal_mode.py::test_embedded_loads_without_address_or_key PASSED [ 15%]
tests/unit/test_config_temporal_mode.py::test_embedded_keeps_namespace_and_task_queue PASSED [ 17%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_the_api_key PASSED [ 20%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_remote_only_keys[address = "localhost:7233"-temporal.address] PASSED [ 23%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_remote_only_keys[tls = true-temporal.tls] PASSED [ 25%]
tests/unit/test_config_temporal_mode.py::test_misspelled_mode_is_reported_before_the_missing_key PASSED [ 28%]
tests/unit/test_config_temporal_mode.py::test_database_defaults_beside_the_store PASSED [ 30%]
tests/unit/test_config_temporal_mode.py::test_database_path_is_configurable PASSED [ 33%]
tests/unit/test_config_temporal_mode.py::test_persist_false_means_no_database PASSED [ 35%]
tests/unit/test_config_temporal_mode.py::test_binary_path_must_exist PASSED [ 38%]
tests/unit/test_config_temporal_mode.py::test_binary_path_must_be_executable PASSED [ 41%]
tests/unit/test_config_temporal_mode.py::test_executable_binary_path_is_accepted PASSED [ 43%]
tests/unit/test_config_temporal_mode.py::test_secret_values_skip_the_absent_temporal_key PASSED [ 46%]
tests/unit/test_config_temporal_mode.py::test_the_demo_embedded_config_loads_without_a_temporal_key PASSED [ 48%]
tests/unit/service/test_embedded_temporal.py::test_starts_on_loopback_with_the_persisted_database PASSED [ 51%]
tests/unit/service/test_embedded_temporal.py::test_in_memory_passes_no_database_and_takes_no_lock PASSED [ 53%]
tests/unit/service/test_embedded_temporal.py::test_binary_path_is_passed_through PASSED [ 56%]
tests/unit/service/test_embedded_temporal.py::test_a_new_database_is_owner_only PASSED [ 58%]
tests/unit/service/test_embedded_temporal.py::test_database_and_lock_are_owner_only PASSED [ 61%]
tests/unit/service/test_embedded_temporal.py::test_a_second_owner_of_the_same_state_is_refused PASSED [ 64%]
tests/unit/service/test_embedded_temporal.py::test_start_failure_is_wrapped_and_releases_the_lock PASSED [ 66%]
tests/unit/service/test_embedded_temporal.py::test_logs_the_start_the_warning_and_the_download PASSED [ 69%]
tests/unit/service/test_embedded_temporal.py::test_no_download_notice_when_the_binary_is_cached PASSED [ 71%]
tests/unit/service/test_embedded_temporal.py::test_default_download_dir_is_private_and_not_in_tmp PASSED [ 74%]
tests/unit/service/test_embedded_temporal.py::test_download_dir_is_created_owner_only PASSED [ 76%]
tests/unit/service/test_embedded_temporal.py::test_a_download_dir_others_can_write_is_refused PASSED [ 79%]
tests/unit/service/test_cli.py::test_every_command_parses PASSED         [ 82%]
tests/unit/service/test_cli.py::test_missing_secret_exits_non_zero_with_the_variable_name PASSED [ 84%]
tests/unit/service/test_cli.py::test_worker_is_refused_in_embedded_mode PASSED [ 87%]
tests/unit/service/test_cli.py::test_admin_commands_are_refused_on_in_memory_state[command0] PASSED [ 89%]
tests/unit/service/test_cli.py::test_admin_commands_are_refused_on_in_memory_state[command1] PASSED [ 92%]
tests/unit/service/test_cli.py::test_embedded_api_key_is_a_config_error PASSED [ 94%]
tests/unit/service/test_cli.py::test_embedded_start_failure_exits_one_with_the_cause PASSED [ 97%]
tests/unit/service/test_cli.py::test_sigterm_cancels_the_command_so_its_cleanup_runs PASSED [100%]
============================== 39 passed in 2.83s ==============================
````
