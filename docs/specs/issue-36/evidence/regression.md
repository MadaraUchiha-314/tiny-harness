# T6 — regression (R7: existing behaviour unchanged)

2026-10-13, branch `loop/issue-36`, Python 3.14, local Temporal dev server (`start_local`).

## `uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui`

```text
9 snapshots passed.
902 passed in 241.23s (0:04:01)
exit=0
```

The first full run found two failures, both in new tests and both test bugs. Neither
was an isolation breach:

- `test_agent_a_treats_every_task_of_agent_b_as_unknown` compared b's task state
  before and after while b's own turn was still moving it from SUBMITTED to WORKING.
  The test now waits for b's task to park before it probes.
- The two log-capture tests relied on `configure_logging`, which keeps the first
  stream it was given in a process. They now attach a handler of their own.

## Existing tests edited, with reasons

| File | Edit | Reason |
|---|---|---|
| `tests/integration/embedded/conftest.py` | The `script_model` fixture patches `tiny_harness.service.harness.build_runtime` instead of `tiny_harness.service.process.build_runtime` | `running_harness` now builds through `Harness` (R7.1). The seam moved, not the behaviour |
| `tests/contract/test_service_api.py` | Docstring names the new exports | Documentation only |
| `tests/integration/test_package.py` | A new test function was added; the existing one is unchanged | T7 |

No existing test needed a change for `runtime.AGENT_ID`: none imported it.
