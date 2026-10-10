# Integration tests — T2

Temporal's time-skipping test server (`WorkflowEnvironment.start_time_skipping()`, binary
cached under `~/.cache/temporalio`), the fixture MCP server over stdio, `FakeLLM`, and the
A2A server in-process over `httpx.ASGITransport`. Run on 2026-10-10 at the head of the
Layer 9 stack.

## Run

```text
## uv run pytest tests/integration -q
32 passed, 304 warnings in 50.94s
```

The warnings are Pydantic deprecation notices raised inside `temporalio`'s payload
converter, not in tiny-harness.

## Scenarios

`the-loop scenarios --root . --glob 'tests/integration/**/*.py' --format markdown`:

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | A2A server | SendStreamingMessage streams a Task then status updates through the bridge | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:90 |
| 2 | A2A server | GetTask and ListTasks read the workflow | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:121 |
| 3 | A2A server | an unadvertised extension is rejected | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:141 |
| 4 | A2A server | returnImmediately returns after the task exists | docs/specs/issue-3/requirements.md#R15 | tests/integration/a2a/test_server.py:170 |
| 5 | A2A server | push notification configs receive status updates | docs/specs/issue-3/requirements.md#R15 | tests/integration/a2a/test_server.py:208 |
| 6 | A2A server | cancel emits CANCELED | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:255 |
| 7 | A2A server | SubscribeToTask after a server restart replays the event log | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:291 |
| 8 | A2UI | emit_ui streams A2UI parts and an action from the renderer reaches the task | docs/specs/issue-3/requirements.md#R20 | tests/integration/a2ui/test_a2ui.py:103 |
| 9 | Remote agents | delegation to a remote A2A agent tracks the sub-task state | docs/specs/issue-3/requirements.md#R7 | tests/integration/agents/test_remote_agents.py:46 |
| 10 | Durable core loop | a task runs the loop to completion with recorded activity results | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:43 |
| 11 | Durable core loop | a worker crash mid-activity resumes without a second LLM call | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:77 |
| 12 | Durable core loop | a non-idempotent tool failure is not retried | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:114 |
| 13 | Durable core loop | activity.failed and activity.retried hooks run between workflow-managed attempts | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:156 |
| 14 | Durable core loop | an inbox message to an executing task is drained at the next iteration | docs/specs/issue-3/requirements.md#R15 | tests/integration/durable/test_core_loop.py:204 |
| 15 | Durable core loop | compaction runs before the LLM call when the first message is over budget | docs/specs/issue-3/requirements.md#R10 | tests/integration/durable/test_core_loop.py:237 |
| 16 | Durable core loop | continue-as-new carries the mailbox, event log and pending help request | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:263 |
| 17 | Durable core loop | a parent waits for an unresolved sub-task before completing | docs/specs/issue-3/requirements.md#R8 | tests/integration/durable/test_core_loop.py:316 |
| 18 | Heartbeat | a schedule tick forwards a pull-channel message to its task | docs/specs/issue-3/requirements.md#R16 | tests/integration/heartbeat/test_heartbeat.py:75 |
| 19 | Heartbeat | the heartbeat is a Temporal schedule | docs/specs/issue-3/requirements.md#R16 | tests/integration/heartbeat/test_heartbeat.py:145 |
| 20 | Help requests | a reply on the channel resumes an INPUT_REQUIRED task | docs/specs/issue-3/requirements.md#R12 | tests/integration/help/test_help_requests.py:69 |
| 21 | Help requests | a need that blocks on another participant's work creates a sub-task | docs/specs/issue-3/requirements.md#R12 | tests/integration/help/test_help_requests.py:99 |
| 22 | Help requests | a non-member's channel message is rejected | docs/specs/issue-3/requirements.md#R13 | tests/integration/help/test_help_requests.py:138 |
| 23 | Observability | one span per operation with GenAI attributes crosses the workflow boundary | docs/specs/issue-3/requirements.md#R17 | tests/integration/o11y/test_observability.py:58 |
| 24 | Plugins | the built-in plugin loads first and is overridable by a lower-priority executor | docs/specs/issue-3/requirements.md#R3 | tests/integration/plugins/test_builtin_plugin.py:26 |
| 25 | Plugins | a directory plugin registers its skills, MCP tools, hooks and prompts | docs/specs/issue-3/requirements.md#R3 | tests/integration/plugins/test_plugin_loading.py:44 |
| 26 | Plugins | a programmatic plugin registers the same components | docs/specs/issue-3/requirements.md#R3 | tests/integration/plugins/test_plugin_loading.py:79 |
| 27 | Plugins | a duplicate (id, version) is refused unless the loading order overrides it | docs/specs/issue-3/requirements.md#R3 | tests/integration/plugins/test_plugin_loading.py:119 |
| 28 | Plugins | a loaded skill's MCP tools appear and disappear with load and unload | docs/specs/issue-3/requirements.md#R5 | tests/integration/plugins/test_skill_tools.py:55 |
| 29 | tiny_harness is installable as a package | the built wheel installs and exposes the package version | docs/specs/issue-2/requirements.md#R2 | tests/integration/test_package.py:22 |
| 30 | MCP tools | a stdio MCP server's tools are registered with their schemas | docs/specs/issue-3/requirements.md#R6 | tests/integration/tools/test_mcp.py:27 |
| 31 | MCP tools | a tool's text result is returned untrusted | docs/specs/issue-3/requirements.md#R6 | tests/integration/tools/test_mcp.py:65 |
