# Integration: remote agents (T2)

Run on 2026-10-12T21:46Z at commit `2dc0dac`.

## `uv run pytest tests/integration/agents -v -p no:warnings`

```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0 -- ~/.the-loop/workspace/.worktrees/github.com/MadaraUchiha-314/tiny-harness/github-MadaraUchiha-314-tiny-harness-27/.venv/bin/python
cachedir: .pytest_cache
rootdir: ~/.the-loop/workspace/.worktrees/github.com/MadaraUchiha-314/tiny-harness/github-MadaraUchiha-314-tiny-harness-27
configfile: pyproject.toml
plugins: platformdirs-4.12.4, syrupy-6.1.1, anyio-4.15.1, textual-snapshot-1.0.0, asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=function, asyncio_default_test_loop_scope=function
collecting ... collected 9 items

tests/integration/agents/test_remote_agents.py::test_delegation_to_a_remote_a2a_agent_tracks_the_sub_task_state PASSED [ 11%]
tests/integration/agents/test_remote_updates.py::test_a_third_party_cancel_is_heard_through_push PASSED [ 22%]
tests/integration/agents/test_remote_updates.py::test_without_push_the_stand_in_follows_and_hears_a_completion PASSED [ 33%]
tests/integration/agents/test_remote_updates.py::test_a_card_without_push_is_followed PASSED [ 44%]
tests/integration/agents/test_remote_updates.py::test_a_reply_while_following_cancels_the_follow PASSED [ 55%]
tests/integration/agents/test_remote_updates.py::test_updates_off_keeps_todays_behaviour PASSED [ 66%]
tests/integration/agents/test_remote_updates.py::test_the_push_config_is_deleted_when_the_stand_in_is_cancelled PASSED [ 77%]
tests/integration/agents/test_remote_updates.py::test_a_failed_registration_falls_back_to_follow PASSED [ 88%]
tests/integration/agents/test_remote_updates.py::test_a_remote_resumed_by_a_third_party_wakes_the_model_only_at_its_end PASSED [100%]

============================== 9 passed in 9.48s ===============================
```
