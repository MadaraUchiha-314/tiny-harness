# T2 — integration scenarios

## `uv run pytest tests/integration/agents -v`

```text
tests/integration/agents/test_agents_roster.py::test_the_models_context_lists_a_configured_remote_agent PASSED
tests/integration/agents/test_agents_roster.py::test_a_spawn_subtask_naming_an_unknown_agent_is_refused_without_a_sub_task PASSED
tests/integration/agents/test_agents_roster.py::test_a_spawn_subtask_naming_a_listed_agent_still_delegates_to_it PASSED
tests/integration/agents/test_agents_roster.py::test_the_durable_engine_renders_the_same_agents_section_on_every_turn PASSED
tests/integration/agents/test_agents_roster.py::test_startup_logs_the_roster_and_each_truncated_card_field PASSED
tests/integration/agents/test_agents_roster.py::test_a_hostile_agent_card_cannot_break_out_of_the_agents_roster PASSED
tests/integration/agents/test_remote_agents.py::test_delegation_to_a_remote_a2a_agent_tracks_the_sub_task_state PASSED
tests/integration/agents/test_remote_updates.py::test_a_third_party_cancel_is_heard_through_push PASSED
tests/integration/agents/test_remote_updates.py::test_without_push_the_stand_in_follows_and_hears_a_completion PASSED
tests/integration/agents/test_remote_updates.py::test_a_card_without_push_is_followed PASSED
tests/integration/agents/test_remote_updates.py::test_a_reply_while_following_cancels_the_follow PASSED
tests/integration/agents/test_remote_updates.py::test_updates_off_keeps_todays_behaviour PASSED
tests/integration/agents/test_remote_updates.py::test_the_push_config_is_deleted_when_the_stand_in_is_cancelled PASSED
tests/integration/agents/test_remote_updates.py::test_a_failed_registration_falls_back_to_follow PASSED
tests/integration/agents/test_remote_updates.py::test_a_remote_resumed_by_a_third_party_wakes_the_model_only_at_its_end PASSED
tests/integration/agents/test_remote_updates.py::test_a_redacted_status_text_does_not_spin_the_follow PASSED
tests/integration/agents/test_remote_updates.py::test_a_failed_cleanup_still_ends_in_the_state_reached PASSED
tests/integration/agents/test_remote_updates.py::test_a_long_parked_stand_in_continues_as_new PASSED
tests/integration/agents/test_remote_updates.py::test_a_fetch_failing_on_the_last_recheck_leaves_the_stand_in_working PASSED
tests/integration/agents/test_remote_updates.py::test_pushes_during_a_turn_are_applied_after_it PASSED
====================== 20 passed, 359 warnings in 47.91s =======================
```

## Scenarios (`the-loop scenarios --root "$PWD" --glob 'tests/integration/agents/*.py' --format markdown`, issue-34 rows)

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | The model sees the configured remote agents | The model's context lists a configured remote agent | docs/specs/issue-34/requirements.md#R1 | tests/integration/agents/test_agents_roster.py:138 |
| 2 | The model sees the configured remote agents | A spawn_subtask naming an unknown agent is refused without a sub-task | docs/specs/issue-34/requirements.md#R3 | tests/integration/agents/test_agents_roster.py:169 |
| 3 | The model sees the configured remote agents | A spawn_subtask naming a listed agent still delegates to it | docs/specs/issue-34/requirements.md#R3 | tests/integration/agents/test_agents_roster.py:201 |
| 4 | The model sees the configured remote agents | The durable engine renders the same agents section on every turn | docs/specs/issue-34/requirements.md#non-functional-requirements | tests/integration/agents/test_agents_roster.py:230 |
| 5 | The model sees the configured remote agents | Startup logs the roster and each truncated card field | docs/specs/issue-34/requirements.md#R4 | tests/integration/agents/test_agents_roster.py:268 |
| 6 | The model sees the configured remote agents | A hostile agent card cannot break out of the agents roster | docs/specs/issue-34/requirements.md#security-considerations | tests/integration/agents/test_agents_roster.py:289 |

## After R5 (PR review): `[card]`

One scenario added for R5. `uv run pytest tests/integration`: 112 passed in 160 s
(before: 111). The scenario table, regenerated:

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | The model sees the configured remote agents | The model's context lists a configured remote agent | docs/specs/issue-34/requirements.md#R1 | tests/integration/agents/test_agents_roster.py:139 |
| 2 | The model sees the configured remote agents | A spawn_subtask naming an unknown agent is refused without a sub-task | docs/specs/issue-34/requirements.md#R3 | tests/integration/agents/test_agents_roster.py:170 |
| 3 | The model sees the configured remote agents | A spawn_subtask naming a listed agent still delegates to it | docs/specs/issue-34/requirements.md#R3 | tests/integration/agents/test_agents_roster.py:202 |
| 4 | The model sees the configured remote agents | The durable engine renders the same agents section on every turn | docs/specs/issue-34/requirements.md#non-functional-requirements | tests/integration/agents/test_agents_roster.py:231 |
| 5 | The model sees the configured remote agents | Startup logs the roster and each truncated card field | docs/specs/issue-34/requirements.md#R4 | tests/integration/agents/test_agents_roster.py:269 |
| 6 | The model sees the configured remote agents | A hostile agent card cannot break out of the agents roster | docs/specs/issue-34/requirements.md#security-considerations | tests/integration/agents/test_agents_roster.py:290 |
| 7 | The model sees the configured remote agents | A tiny-harness described by its card section is listed by another | docs/specs/issue-34/requirements.md#R5 | tests/integration/agents/test_agents_roster.py:322 |

## After R7 (PR review): every child over A2A

- New: `tests/integration/agents/test_self_delegation.py` — *A sub-task on itself goes
  through its own A2A interface and returns its result* (R7).
- The child-task scenarios (`durable/test_core_loop`, `test_conversation_lifecycle`,
  `test_sub_tasks`, `test_builtin_commands`, `test_commands`, `test_complete`,
  `help/test_help_requests`, `a2a/test_command_stream`) run on the harness's own A2A app
  (`self_hosted`); every test server registers `self`, as `build_runtime` does.
- The remote-agent scenarios use `tests/integration/streaming_asgi.py`: an in-process
  transport that streams like a socket. `httpx.ASGITransport` buffered a response to its
  end, which had hidden that a follow read `SubscribeToTask`'s replayed history as a
  change.
- `uv run pytest tests/integration`: 113 passed.
