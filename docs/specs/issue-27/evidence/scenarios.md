# Scenario table (T2)

Run on 2026-10-12T21:48Z at commit `2dc0dac`.

## `the-loop scenarios --root "$PWD" --glob 'tests/integration/agents/*.py' --format markdown`

```text
| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | Remote agents | delegation to a remote A2A agent tracks the sub-task state | docs/specs/issue-3/requirements.md#R7 | tests/integration/agents/test_remote_agents.py:55 |
| 2 | Remote sub-tasks hear remote state changes between turns | A third party cancels a parked remote sub-task and the parent hears of it through push | docs/specs/issue-27/requirements.md#R2 | tests/integration/agents/test_remote_updates.py:56 |
| 3 | Remote sub-tasks hear remote state changes between turns | Without push the stand-in follows the parked task and hears a third-party completion | docs/specs/issue-27/requirements.md#R3 | tests/integration/agents/test_remote_updates.py:93 |
| 4 | Remote sub-tasks hear remote state changes between turns | updates = "auto" follows a remote agent whose card advertises no push | docs/specs/issue-27/requirements.md#R4 | tests/integration/agents/test_remote_updates.py:121 |
| 5 | Remote sub-tasks hear remote state changes between turns | A reply while following cancels the follow and starts a turn | docs/specs/issue-27/requirements.md#R3 | tests/integration/agents/test_remote_updates.py:147 |
| 6 | Remote sub-tasks hear remote state changes between turns | updates = "off" keeps today's behaviour | docs/specs/issue-27/requirements.md#R4 | tests/integration/agents/test_remote_updates.py:176 |
| 7 | Remote sub-tasks hear remote state changes between turns | The push config is deleted when the stand-in is cancelled | docs/specs/issue-27/requirements.md#R5 | tests/integration/agents/test_remote_updates.py:203 |
| 8 | Remote sub-tasks hear remote state changes between turns | A failed registration falls back to follow | docs/specs/issue-27/requirements.md#R1 | tests/integration/agents/test_remote_updates.py:229 |
| 9 | Remote sub-tasks hear remote state changes between turns | The parent's row moves and its model is told only of an ending or a new question | docs/specs/issue-27/requirements.md#R2 | tests/integration/agents/test_remote_updates.py:260 |
```
