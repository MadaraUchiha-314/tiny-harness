---
type: evidence
workItem: issue-23
row: T1
---

# Unit tests (T1)

All unit tests pass at `34dccbc` with `TINY_HARNESS_PUSH_KEY` unset: 358 passed.
Run on 2026-10-11 with `TMPDIR` under the home directory (the machine's `/tmp` was at its
per-user quota, unrelated to this change).

## Full unit suite

```text
$ env -u TINY_HARNESS_PUSH_KEY uv run pytest tests/unit -q
358 passed in 4.34s
```

## The files this work item touched

```text
$ uv run pytest -q tests/unit/test_config.py tests/unit/test_config_openai.py \
    tests/unit/test_config_temporal_mode.py tests/unit/service/test_runtime_model.py \
    tests/unit/service/test_cli.py tests/unit/persistence/test_sqlite.py \
    tests/unit/service/test_app_routes.py
106 passed in 3.15s
```

| Test | What it proves | Requirement |
|------|----------------|-------------|
| `test_config.py::test_no_push_key_is_read_or_required` | `Settings` has no `push_key`; loads without the variable and ignores it when set | R1.1, R1.2 |
| `test_runtime_model.py::test_an_exported_push_key_is_warned_about_without_its_value` | one "set and ignored" line, value absent | R1.3, abuse 3 |
| `test_runtime_model.py::test_both_ignored_variables_are_reported`, `test_no_warning_without_the_variable` | the table reports each set variable, nothing for unset or empty | R1.3 |
| `test_cli.py::test_missing_secret_exits_non_zero_with_the_variable_name` | the required secrets are the Temporal and OpenAI keys only | R1.2 |
| `test_sqlite.py::test_no_record_has_a_credential_field` | the only credential fields are the push config's, typed `SecretStr`; the 0.5.x ciphertext fields are never written | R3.1, R4 |
| `test_config_openai.py`, `test_config_temporal_mode.py` (`secret_values`) | the redactor's secret list no longer includes a push key | R1.1 |

## Red before green

Before the change, the rewritten config fixtures (no `TINY_HARNESS_PUSH_KEY`) failed:
`72 failed, 286 passed` — every `Settings.load` raised the missing-variable
`ConfigError`.
