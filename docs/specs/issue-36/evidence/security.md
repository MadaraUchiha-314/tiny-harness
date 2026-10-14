# T4 — security and abuse cases

2026-10-13, branch `loop/issue-36`, Python 3.14, local Temporal dev server (`start_local`).

## `uv run pytest tests/security/test_multi_agent_isolation.py tests/security/test_participant_resolver.py -v`

```text
tests/security/test_multi_agent_isolation.py::test_agent_a_treats_every_task_of_agent_b_as_unknown PASSED [ 16%]
tests/security/test_multi_agent_isolation.py::test_a_push_for_agent_bs_workflow_at_agent_as_route_is_refused PASSED [ 33%]
tests/security/test_multi_agent_isolation.py::test_a_second_harness_on_the_same_namespace_and_queue_does_not_start PASSED [ 50%]
tests/security/test_multi_agent_isolation.py::test_a_request_before_start_never_reaches_temporal PASSED [ 66%]
tests/security/test_multi_agent_isolation.py::test_one_agents_log_masks_another_agents_key PASSED [ 83%]
tests/security/test_participant_resolver.py::test_with_a_resolver_a_spoofed_participant_header_is_ignored PASSED [100%]
exit=0
```

| Abuse case (requirements § Security considerations) | Test | Outcome |
|---|---|---|
| 1 Header spoofing with a resolver | `test_with_a_resolver_a_spoofed_participant_header_is_ignored` | Reporter is the resolved user. bob cannot read alice's task. An unauthenticated message claiming alice in metadata is refused (400, `no participant asserted`) |
| 2 Cross-agent task access | `test_agent_a_treats_every_task_of_agent_b_as_unknown` | GetTask, CancelTask, SubscribeToTask, four push-config operations and SendMessage with b's task id on agent a: all 404 `TASK_NOT_FOUND`. ListTasks on a omits it. b's task state unchanged. No push config stored |
| 3 Push to the wrong agent | `test_a_push_for_agent_bs_workflow_at_agent_as_route_is_refused` (+ unit `test_a_push_for_another_agents_stand_in_is_refused_without_an_update`) | 401, no update sent |
| 4 Shared queue | `test_a_second_harness_on_the_same_namespace_and_queue_does_not_start` | `HarnessConflictError` naming the queue and holder; not started; no claim held |
| 5 Request before start | `test_a_request_before_start_never_reaches_temporal` | 503 for message, lookup and push; a client that fails on any access was never touched |
| 6 Cross-agent secret leak | `test_one_agents_log_masks_another_agents_key` | b's key masked by a's redactor and by the log formatter; unregistered after b stops |
