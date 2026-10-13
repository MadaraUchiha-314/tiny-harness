# T3 — acceptance: five agents in one app

The issue author's test ([PR #37 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/37#issuecomment-6150070351)):
five configurations, five agents with their own endpoints, each able to use the others
through its configuration, in one service.

2026-10-13, branch `loop/issue-36`, Python 3.14, local Temporal dev server (`start_local`). The five configurations are `examples/multi_agent/a.toml` … `e.toml`, rewritten
only for the test's port and temporary directory. Models are scripted. Temporal is one
embedded dev server from the process's `TemporalPool`; each run asserts
`PROCESS_POOL.open_connections() == 1`.

## `uv run pytest tests/integration/mount/test_multi_agent.py -v`

```text
tests/integration/mount/test_multi_agent.py::test_five_agents_in_one_app_delegate_to_each_other[starlette] PASSED [ 33%]
tests/integration/mount/test_multi_agent.py::test_five_agents_in_one_app_delegate_to_each_other[fastapi] PASSED [ 66%]
tests/integration/mount/test_multi_agent.py::test_a_parked_sub_task_on_agent_b_pushes_to_agent_as_prefixed_route PASSED [100%]
exit=0
```

What each scenario proves:

| Scenario | Proof |
|----------|-------|
| five agents in one app delegate to each other `[starlette]` | All five cards are served at `<origin>/agents/<id>/`. a delegates to b over HTTP and is told b's reply. b delegates to d and is told d's reply. c and e ran no task. d's tasks name b as a participant |
| five agents in one app delegate to each other `[fastapi]` | The same, with `harness_router` per agent in one FastAPI app |
| A parked sub-task on agent b pushes to agent a's prefixed route | b parks its task asking a a question. a's stand-in registers `<origin>/agents/a/a2a/push/<id>` on b's task. A third party cancels b's task, b's push wakes a's stand-in, and a's sub-task ends CANCELED |
