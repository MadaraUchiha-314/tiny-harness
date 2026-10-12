# Migration and upgrade

Issue #25, verification run on 2026-10-12 against `loop/issue-25` at `2393e75`.
Testing-plan rows: T10.

`uv run pytest tests/unit/core/test_task_compat.py tests/unit/test_config.py -v`

```text
tests/unit/core/test_task_compat.py::test_a_pre_change_task_loads_from_the_store_and_answers_get_task PASSED [ 11%]
tests/unit/test_config.py::test_no_push_key_is_read_or_required PASSED   [ 22%]
tests/unit/test_config.py::test_loads_toml_and_secrets_with_typed_defaults PASSED [ 33%]
tests/unit/test_config.py::test_missing_secret_names_variable PASSED     [ 44%]
tests/unit/test_config.py::test_unknown_key_rejected PASSED              [ 55%]
tests/unit/test_config.py::test_secrets_never_print PASSED               [ 66%]
tests/unit/test_config.py::test_optional_secrets_fill_their_sections PASSED [ 77%]
tests/unit/test_config.py::test_missing_file_and_invalid_toml_are_config_errors PASSED [ 88%]
tests/unit/test_config.py::test_a_pre_issue_25_file_loads_unchanged PASSED [100%]
============================== 9 passed in 5.30s ===============================
```

- A task stored before this change, with no `lifecycle` and no status key, still loads
  and `GetTask` answers. Its lifecycle is derived from `parent_tasks`.
- An existing `--config` file loads unchanged; the new `[openai] models` and
  `reasoning_effort` keys are optional.
