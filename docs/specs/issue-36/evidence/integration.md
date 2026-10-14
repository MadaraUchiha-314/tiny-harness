# T2 — integration scenarios (mounted agents)

2026-10-13, branch `loop/issue-36`, Python 3.14, local Temporal dev server (`start_local`).

## `uv run pytest tests/integration/mount -v`

```text
tests/integration/mount/test_fastapi.py::test_a_fastapi_app_includes_an_agent_router_and_lists_its_routes_in_openapi PASSED [  7%]
tests/integration/mount/test_fastapi.py::test_a_router_answers_503_before_start_and_enforces_its_limits PASSED [ 14%]
tests/integration/mount/test_fastapi.py::test_a_router_included_under_another_prefix_refuses_every_request PASSED [ 21%]
tests/integration/mount/test_multi_agent.py::test_five_agents_in_one_app_delegate_to_each_other[starlette] PASSED [ 28%]
tests/integration/mount/test_multi_agent.py::test_five_agents_in_one_app_delegate_to_each_other[fastapi] PASSED [ 35%]
tests/integration/mount/test_multi_agent.py::test_a_parked_sub_task_on_agent_b_pushes_to_agent_as_prefixed_route PASSED [ 42%]
tests/integration/mount/test_starlette.py::test_a_harness_starts_from_a_host_lifespan_and_opens_no_port PASSED [ 50%]
tests/integration/mount/test_starlette.py::test_an_agent_mounted_under_a_prefix_serves_its_card_with_prefixed_urls PASSED [ 57%]
tests/integration/mount/test_starlette.py::test_a_mounted_agent_answers_503_until_its_harness_has_started PASSED [ 64%]
tests/integration/mount/test_starlette.py::test_an_agent_mounted_at_the_wrong_path_refuses_every_request PASSED [ 71%]
tests/integration/mount/test_starlette.py::test_a_top_level_harness_app_starts_itself_from_the_server_lifespan PASSED [ 78%]
tests/integration/mount/test_starlette.py::test_with_the_push_route_off_a_remote_sub_task_is_followed PASSED [ 85%]
tests/integration/mount/test_starlette.py::test_several_harnesses_start_and_stop_in_order_from_one_lifespan PASSED [ 92%]
tests/integration/mount/test_starlette.py::test_each_log_line_names_the_agent_that_wrote_it PASSED [100%]
exit=0
```

## Scenario table

`the-loop scenarios --root "$PWD" --glob "tests/integration/mount/*.py" --glob
"tests/security/test_multi_agent_isolation.py" --glob
"tests/security/test_participant_resolver.py" --glob "tests/integration/test_package.py"
--format markdown`

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | an agent included in a host FastAPI app | A FastAPI app includes an agent router and lists its routes in OpenAPI | docs/specs/issue-36/requirements.md#R3 | tests/integration/mount/test_fastapi.py:44 |
| 2 | an agent included in a host FastAPI app | A router answers 503 before start and enforces its limits | docs/specs/issue-36/requirements.md#R3, #R4 | tests/integration/mount/test_fastapi.py:97 |
| 3 | an agent included in a host FastAPI app | A router included under another prefix refuses every request | docs/specs/issue-36/requirements.md#R3 | tests/integration/mount/test_fastapi.py:126 |
| 4 | five agents in one app | five agents in one app delegate to each other | docs/specs/issue-36/requirements.md#R5, #R6 | tests/integration/mount/test_multi_agent.py:130 |
| 5 | five agents in one app | A parked sub-task on agent b pushes to agent a's prefixed route | docs/specs/issue-36/requirements.md#R6 | tests/integration/mount/test_multi_agent.py:187 |
| 6 | an agent mounted on a host Starlette app | A harness starts from a host lifespan and opens no port | docs/specs/issue-36/requirements.md#R1, #R2, #R4 | tests/integration/mount/test_starlette.py:50 |
| 7 | an agent mounted on a host Starlette app | An agent mounted under a prefix serves its card with prefixed URLs | docs/specs/issue-36/requirements.md#R2, #R4 | tests/integration/mount/test_starlette.py:88 |
| 8 | an agent mounted on a host Starlette app | A mounted agent answers 503 until its harness has started | docs/specs/issue-36/requirements.md#R2 | tests/integration/mount/test_starlette.py:114 |
| 9 | an agent mounted on a host Starlette app | An agent mounted at the wrong path refuses every request | docs/specs/issue-36/requirements.md#R2 | tests/integration/mount/test_starlette.py:141 |
| 10 | an agent mounted on a host Starlette app | A top-level harness app starts itself from the server lifespan | docs/specs/issue-36/requirements.md#R2, #R7 | tests/integration/mount/test_starlette.py:169 |
| 11 | an agent mounted on a host Starlette app | With the push route off a remote sub-task is followed | docs/specs/issue-36/requirements.md#R4 | tests/integration/mount/test_starlette.py:193 |
| 12 | an agent mounted on a host Starlette app | Several harnesses start and stop in order from one lifespan | docs/specs/issue-36/requirements.md#R5 | tests/integration/mount/test_starlette.py:222 |
| 13 | an agent mounted on a host Starlette app | Each log line names the agent that wrote it | docs/specs/issue-36/requirements.md#R5 (non-functional: observability) | tests/integration/mount/test_starlette.py:251 |
| 14 | agents in one process are isolated from each other | Agent a treats every task of agent b as unknown | docs/specs/issue-36/requirements.md#R5 (Security considerations, abuse case 2) | tests/security/test_multi_agent_isolation.py:102 |
| 15 | agents in one process are isolated from each other | A push for agent b's stand-in at agent a's route is refused | docs/specs/issue-36/requirements.md#R5 (abuse case 3) | tests/security/test_multi_agent_isolation.py:158 |
| 16 | agents in one process are isolated from each other | A second harness on the same namespace and queue does not start | docs/specs/issue-36/requirements.md#R5 (abuse case 4) | tests/security/test_multi_agent_isolation.py:182 |
| 17 | agents in one process are isolated from each other | A request before start never reaches Temporal | docs/specs/issue-36/requirements.md#R2 (abuse case 5) | tests/security/test_multi_agent_isolation.py:221 |
| 18 | agents in one process are isolated from each other | One agent's log masks another agent's key | docs/specs/issue-36/requirements.md#R5 (abuse case 6) | tests/security/test_multi_agent_isolation.py:249 |
| 19 | the host app's authentication names the participant | With a resolver a spoofed participant header is ignored | docs/specs/issue-36/requirements.md#R4 (Security considerations, abuse case 1) | tests/security/test_participant_resolver.py:80 |
| 20 | tiny_harness is installable as a package | the built wheel installs and exposes the package version | docs/specs/issue-2/requirements.md#R2 | tests/integration/test_package.py:22 |
| 21 | tiny_harness is installable as a package | the FastAPI helper needs its extra | docs/specs/issue-36/requirements.md#R3 | tests/integration/test_package.py:64 |
