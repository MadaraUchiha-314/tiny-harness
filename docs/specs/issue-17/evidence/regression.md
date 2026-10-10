# Regression

Work item: issue-17 · testing-plan row T10 · commit `cdd0785` · run 2026-10-10 on Linux (Python 3.14, temporalio 1.34.0, Temporal CLI 1.9.1).

## Pre-commit on every file (CI's lint job)

```sh
PATH="$PWD/.venv/bin:$PATH" uv run pre-commit run --all-files
```

Exit status `0` in 24.6 s.

````text
ruff (lint + autofix)....................................................Passed
ruff (format)............................................................Passed
pyright (type check).....................................................Passed
pytest (unit tests)......................................................Passed
markdownlint.............................................................Passed
````

## CI's test commands

```sh
uv run pytest tests/integration tests/contract tests/security tests/ui -q --basetemp ~/.cache/tiny-harness-pytest/run
```

Exit status `0` in 87.9 s (last 4 of 33 lines).

````text
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
--------------------------- snapshot report summary ----------------------------
4 snapshots passed.
112 passed, 375 warnings in 85.59s (0:01:25)
````

## The remote demo config still loads as remote and still needs the key

```sh
uv run pytest tests/unit/test_config_temporal_mode.py -v -k 'absent_mode or remote' 2>&1 | grep -E 'PASSED|FAILED|passed|failed'; git diff --stat origin/main -- examples/demo/config.toml; echo 'config.toml diff against main: (empty above = unchanged)'
```

Exit status `0` in 0.8 s.

````text
tests/unit/test_config_temporal_mode.py::test_absent_mode_is_remote_and_unchanged PASSED [ 14%]
tests/unit/test_config_temporal_mode.py::test_remote_still_requires_the_api_key PASSED [ 28%]
tests/unit/test_config_temporal_mode.py::test_remote_requires_address_and_namespace[address] PASSED [ 42%]
tests/unit/test_config_temporal_mode.py::test_remote_requires_address_and_namespace[namespace] PASSED [ 57%]
tests/unit/test_config_temporal_mode.py::test_remote_refuses_the_embedded_table PASSED [ 71%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_remote_only_keys[address = "localhost:7233"-temporal.address] PASSED [ 85%]
tests/unit/test_config_temporal_mode.py::test_embedded_refuses_remote_only_keys[tls = true-temporal.tls] PASSED [100%]
======================= 7 passed, 12 deselected in 0.13s =======================
config.toml diff against main: (empty above = unchanged)
````
