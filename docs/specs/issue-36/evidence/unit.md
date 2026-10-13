# T1 — unit tests

2026-10-13, branch `loop/issue-36`, Python 3.14, local Temporal dev server (`start_local`).

## `uv run pytest tests/unit`

```text
632 passed in 9.31s
exit=0
```

New unit tests for issue-36: `test_config_agent.py`, `service/test_claims.py`,
`service/test_pool.py`, `test_redactor_registry.py`, `service/test_logging_agent.py`,
`service/test_task_ownership.py`, `service/test_push_receiver.py` (ownership cases),
`service/test_heartbeat_id.py`, `service/test_context_builder.py`,
`service/test_public_url.py`, `service/test_harness_app.py`,
`service/test_harness_lifecycle.py`, `test_errors.py` (lifecycle errors).

Mutation check: with the queue ownership check removed from `Harness` (the task store
built without `task_queue`), `test_agent_a_treats_every_task_of_agent_b_as_unknown`
fails. It passes again with the check restored.
