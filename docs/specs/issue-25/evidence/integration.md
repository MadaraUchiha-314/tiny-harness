# Integration tests

Issue #25, verification run on 2026-10-12 against `loop/issue-25` at `2393e75`.
Testing-plan rows: T2.

`uv run pytest tests/integration` (Temporal's time-skipping test server, the local dev
server, and embedded mode; every model is scripted)

```text
86 passed, 626 warnings in 79.58s (0:01:19)
rc=0 secs=81
```

## Scenarios

`the-loop scenarios --root "$PWD" --glob 'tests/integration/**/*.py' --format markdown`

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | A2A server | no asserted participant is refused everywhere | docs/specs/issue-3/requirements.md#R14 (abuse case 4) | tests/integration/a2a/test_access.py:92 |
| 2 | Commands over the A2A server | A command that changes the task replies on the sender's stream | docs/specs/issue-25/requirements.md#R9 | tests/integration/a2a/test_command_stream.py:59 |
| 3 | SubscribeToTask | A subscriber to a parked conversation stays attached for live events | docs/specs/issue-3/requirements.md#R20 | tests/integration/a2a/test_command_stream.py:127 |
| 4 | A2A server | SendStreamingMessage streams a Task then status updates through the bridge | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:99 |
| 5 | A2A server | GetTask and ListTasks read the workflow | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:134 |
| 6 | A2A server | an unadvertised extension is rejected | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:156 |
| 7 | A2A server | returnImmediately returns after the task exists | docs/specs/issue-3/requirements.md#R15 | tests/integration/a2a/test_server.py:185 |
| 8 | A2A server | push notification configs receive status updates | docs/specs/issue-3/requirements.md#R15 | tests/integration/a2a/test_server.py:218 |
| 9 | A2A server | a push config's credentials round-trip through get, list and delete | docs/specs/issue-23/requirements.md#R2 | tests/integration/a2a/test_server.py:289 |
| 10 | A2A server | a push config stored encrypted by an earlier version is dropped, not delivered | docs/specs/issue-23/requirements.md#R4 | tests/integration/a2a/test_server.py:344 |
| 11 | A2A server | cancel emits CANCELED | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:390 |
| 12 | A2A server | SubscribeToTask after a server restart replays the event log | docs/specs/issue-3/requirements.md#R14 | tests/integration/a2a/test_server.py:426 |
| 13 | A2UI | emit_ui streams A2UI parts and an action from the renderer reaches the task | docs/specs/issue-3/requirements.md#R20 | tests/integration/a2ui/test_a2ui.py:103 |
| 14 | Remote agents | delegation to a remote A2A agent tracks the sub-task state | docs/specs/issue-3/requirements.md#R7 | tests/integration/agents/test_remote_agents.py:55 |
| 15 | OpenAI-compatible endpoints | Harness completes a task against an OpenAI-compatible Responses endpoint | docs/specs/issue-19/requirements.md#R3 | tests/integration/compat/test_compat_endpoint.py:68 |
| 16 | OpenAI-compatible endpoints | Harness completes a task against an OpenAI-compatible Chat Completions endpoint | docs/specs/issue-19/requirements.md#R3 | tests/integration/compat/test_compat_endpoint.py:94 |
| 17 | OpenAI-compatible endpoints | A retryable endpoint failure is retried and the task completes | docs/specs/issue-19/requirements.md#R5 | tests/integration/compat/test_compat_endpoint.py:122 |
| 18 | Built-in commands | /sub-task creates a linked conversation task and replies with its id | docs/specs/issue-25/requirements.md#R9 | tests/integration/durable/test_builtin_commands.py:84 |
| 19 | Built-in commands | a participant's /sub-task is noted in the parent's history | docs/specs/issue-25/requirements.md#R9 | tests/integration/durable/test_builtin_commands.py:132 |
| 20 | Built-in commands | /model and /effort sent as commands change the next model request | docs/specs/issue-25/requirements.md#R7 | tests/integration/durable/test_builtin_commands.py:172 |
| 21 | Built-in commands | A plugin command overrides a built-in and a pre hook can refuse it | docs/specs/issue-25/requirements.md#R6a | tests/integration/durable/test_builtin_commands.py:213 |
| 22 | Built-in commands | A remote command executor that fails leaves the task unchanged | docs/specs/issue-25/requirements.md#R6a | tests/integration/durable/test_builtin_commands.py:275 |
| 23 | Slash commands | A command runs without invoking the model and the state is unchanged | docs/specs/issue-25/requirements.md#R6 | tests/integration/durable/test_commands.py:93 |
| 24 | Slash commands | A command sent during a running turn replies without joining the history | docs/specs/issue-25/requirements.md#R6 | tests/integration/durable/test_commands.py:138 |
| 25 | Slash commands | A failing command replies with the error and changes nothing | docs/specs/issue-25/requirements.md#R6 | tests/integration/durable/test_commands.py:176 |
| 26 | Slash commands | A command's intents are applied by the workflow, settings then spawn then reply | docs/specs/issue-25/requirements.md#R9 | tests/integration/durable/test_commands.py:215 |
| 27 | Slash commands | A participant task still completes on the assignee's answer, and a command does not | docs/specs/issue-25/requirements.md#R3 | tests/integration/durable/test_commands.py:275 |
| 28 | Participant completion | A participant completes a task and every subscriber sees COMPLETED | docs/specs/issue-25/requirements.md#R5 | tests/integration/durable/test_complete.py:98 |
| 29 | Participant completion | Completing a task interrupts the turn in progress | docs/specs/issue-25/requirements.md#R5 | tests/integration/durable/test_complete.py:155 |
| 30 | Participant completion | Completing or cancelling a terminal task names its state | docs/specs/issue-25/requirements.md#R5 | tests/integration/durable/test_complete.py:201 |
| 31 | Participant completion | Completion is refused while a sub-task is open | docs/specs/issue-25/requirements.md#R5 | tests/integration/durable/test_complete.py:239 |
| 32 | Conversation task lifecycle | A reply leaves a conversation task awaiting the next message | docs/specs/issue-25/requirements.md#R3 | tests/integration/durable/test_conversation_lifecycle.py:66 |
| 33 | Conversation task lifecycle | The next message resumes the same task and clears the sub-state | docs/specs/issue-25/requirements.md#R3 | tests/integration/durable/test_conversation_lifecycle.py:107 |
| 34 | Conversation task lifecycle | A refused message does not wake a parked conversation | docs/specs/issue-25/requirements.md#R3 | tests/integration/durable/test_conversation_lifecycle.py:157 |
| 35 | Conversation task lifecycle | ask_participant parks the task awaiting an answer | docs/specs/issue-25/requirements.md#R3 | tests/integration/durable/test_conversation_lifecycle.py:193 |
| 36 | Conversation task lifecycle | A delegated sub-task still completes when its loop ends | docs/specs/issue-25/requirements.md#R3 | tests/integration/durable/test_conversation_lifecycle.py:240 |
| 37 | Durable core loop | a task runs the loop to its reply with recorded activity results | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:52 |
| 38 | Durable core loop | a worker crash mid-activity resumes without a second LLM call | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:90 |
| 39 | Durable core loop | a non-idempotent tool failure is not retried | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:128 |
| 40 | Durable core loop | activity.failed and activity.retried hooks run between workflow-managed attempts | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:171 |
| 41 | Durable core loop | an inbox message to an executing task is drained at the next iteration | docs/specs/issue-3/requirements.md#R15 | tests/integration/durable/test_core_loop.py:220 |
| 42 | Durable core loop | compaction runs before the LLM call when the first message is over budget | docs/specs/issue-3/requirements.md#R10 | tests/integration/durable/test_core_loop.py:255 |
| 43 | Durable core loop | continue-as-new carries the mailbox, event log and pending help request | docs/specs/issue-3/requirements.md#R19 | tests/integration/durable/test_core_loop.py:282 |
| 44 | Durable core loop | a parent waits for an unresolved sub-task before completing | docs/specs/issue-3/requirements.md#R8 | tests/integration/durable/test_core_loop.py:336 |
| 45 | Inbox and events | a task envelope updates an existing task within its sender's rights | docs/specs/issue-3/requirements.md#R15 | tests/integration/durable/test_envelopes.py:63 |
| 46 | Per-task model and effort | /model and /effort change the next model request, compaction and help included | docs/specs/issue-25/requirements.md#R7 | tests/integration/durable/test_model_settings.py:58 |
| 47 | Per-task model and effort | A task without settings uses the configured defaults | docs/specs/issue-25/requirements.md#R7 | tests/integration/durable/test_model_settings.py:90 |
| 48 | Per-task model and effort | The compaction budget follows the task's model | docs/specs/issue-25/requirements.md#R7 | tests/integration/durable/test_model_settings.py:113 |
| 49 | Sub-task lifecycle and settings | Sub-tasks inherit the parent's model and effort | docs/specs/issue-25/requirements.md#R7 | tests/integration/durable/test_sub_tasks.py:62 |
| 50 | Sub-task lifecycle and settings | A conversation sub-task with no first message waits for one | docs/specs/issue-25/requirements.md#R9 | tests/integration/durable/test_sub_tasks.py:133 |
| 51 | Embedded Temporal mode | TUI hosts its own harness in embedded mode | docs/specs/issue-17/requirements.md#R5 | tests/integration/embedded/test_cli_embedded.py:73 |
| 52 | TUI participant assertion | TUI sends a message under the asserted participant | docs/specs/issue-20/bugfix.md#R1 | tests/integration/embedded/test_cli_embedded.py:129 |
| 53 | TUI task controls | The real TUI completes a conversation and its sub-task | docs/specs/issue-25/requirements.md#R9 | tests/integration/embedded/test_cli_embedded.py:183 |
| 54 | Embedded Temporal mode | TUI with a URL starts no embedded server | docs/specs/issue-17/requirements.md#R5 | tests/integration/embedded/test_cli_embedded.py:263 |
| 55 | Embedded Temporal mode | Admin commands act on persisted embedded state | docs/specs/issue-17/requirements.md#R5 | tests/integration/embedded/test_cli_embedded.py:292 |
| 56 | Embedded Temporal mode | Embedded server stops when serve receives SIGTERM | docs/specs/issue-17/requirements.md#R2 | tests/integration/embedded/test_cli_embedded.py:326 |
| 57 | Embedded Temporal mode | Embedded server stops when a program running serve receives SIGTERM | docs/specs/issue-17/requirements.md#R6 | tests/integration/embedded/test_cli_embedded.py:400 |
| 58 | Embedded Temporal mode | Embedded mode starts without Temporal credentials | docs/specs/issue-17/requirements.md#R1 | tests/integration/embedded/test_embedded_temporal.py:149 |
| 59 | Embedded Temporal mode | Embedded server binds loopback only | docs/specs/issue-17/requirements.md#R2 | tests/integration/embedded/test_embedded_temporal.py:167 |
| 60 | Embedded Temporal mode | Embedded server stops when the harness exits | docs/specs/issue-17/requirements.md#R2 | tests/integration/embedded/test_embedded_temporal.py:197 |
| 61 | Embedded Temporal mode | Embedded state survives a restart | docs/specs/issue-17/requirements.md#R3 | tests/integration/embedded/test_embedded_temporal.py:230 |
| 62 | Embedded Temporal mode | A second process cannot open the same embedded state | docs/specs/issue-17/design.md#security-design | tests/integration/embedded/test_embedded_temporal.py:263 |
| 63 | Embedded Temporal mode | Programmatic harness runs a task in embedded mode | docs/specs/issue-17/requirements.md#R6 | tests/integration/embedded/test_running_harness.py:105 |
| 64 | Embedded Temporal mode | Embedded server registers search attributes and the heartbeat schedule | docs/specs/issue-17/requirements.md#R2 | tests/integration/embedded/test_running_harness.py:131 |
| 65 | Embedded Temporal mode | An SDK harness serves its own commands and never touches the home directory | docs/specs/issue-25/requirements.md#R11 | tests/integration/embedded/test_running_harness.py:152 |
| 66 | Heartbeat | a schedule tick forwards a pull-channel message to its task | docs/specs/issue-3/requirements.md#R16 | tests/integration/heartbeat/test_heartbeat.py:83 |
| 67 | Heartbeat | the heartbeat is a Temporal schedule | docs/specs/issue-3/requirements.md#R16 | tests/integration/heartbeat/test_heartbeat.py:154 |
| 68 | Help requests | a reply on the channel resumes an INPUT_REQUIRED task | docs/specs/issue-3/requirements.md#R12 | tests/integration/help/test_help_requests.py:78 |
| 69 | Help requests | a need that blocks on another participant's work creates a sub-task | docs/specs/issue-3/requirements.md#R12 | tests/integration/help/test_help_requests.py:109 |
| 70 | Help requests | a non-member's channel message is rejected | docs/specs/issue-3/requirements.md#R13 | tests/integration/help/test_help_requests.py:150 |
| 71 | Observability | one span per operation with GenAI attributes crosses the workflow boundary | docs/specs/issue-3/requirements.md#R17 | tests/integration/o11y/test_observability.py:66 |
| 72 | Plugins | the built-in plugin loads first and is overridable by a lower-priority executor | docs/specs/issue-3/requirements.md#R3 | tests/integration/plugins/test_builtin_plugin.py:26 |
| 73 | Plugins | a directory plugin registers its skills, MCP tools, hooks and prompts | docs/specs/issue-3/requirements.md#R3 | tests/integration/plugins/test_plugin_loading.py:44 |
| 74 | Plugins | a programmatic plugin registers the same components | docs/specs/issue-3/requirements.md#R3 | tests/integration/plugins/test_plugin_loading.py:79 |
| 75 | Plugins | a duplicate (id, version) is refused unless the loading order overrides it | docs/specs/issue-3/requirements.md#R3 | tests/integration/plugins/test_plugin_loading.py:119 |
| 76 | Plugins | a loaded skill's MCP tools appear and disappear with load and unload | docs/specs/issue-3/requirements.md#R5 | tests/integration/plugins/test_skill_tools.py:55 |
| 77 | tiny_harness is installable as a package | the built wheel installs and exposes the package version | docs/specs/issue-2/requirements.md#R2 | tests/integration/test_package.py:22 |
| 78 | MCP tools | a stdio MCP server's tools are registered with their schemas | docs/specs/issue-3/requirements.md#R6 | tests/integration/tools/test_mcp.py:27 |
| 79 | MCP tools | a tool's text result is returned untrusted | docs/specs/issue-3/requirements.md#R6 | tests/integration/tools/test_mcp.py:65 |
