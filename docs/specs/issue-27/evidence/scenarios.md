# Scenario table (T2)

Run on 2026-10-12T23:08Z at commit `f77a3b8`.

## `the-loop scenarios --root "$PWD" --glob 'tests/integration/agents/*.py' --format markdown`

```text
| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | Remote agents | delegation to a remote A2A agent tracks the sub-task state | docs/specs/issue-3/requirements.md#R7 | tests/integration/agents/test_remote_agents.py:55 |
| 2 | Remote sub-tasks hear remote state changes between turns | A third party cancels a parked remote sub-task and the parent hears of it through push | docs/specs/issue-27/requirements.md#R2 | tests/integration/agents/test_remote_updates.py:69 |
| 3 | Remote sub-tasks hear remote state changes between turns | Without push the stand-in follows the parked task and hears a third-party completion | docs/specs/issue-27/requirements.md#R3 | tests/integration/agents/test_remote_updates.py:106 |
| 4 | Remote sub-tasks hear remote state changes between turns | updates = "auto" follows a remote agent whose card advertises no push | docs/specs/issue-27/requirements.md#R4 | tests/integration/agents/test_remote_updates.py:134 |
| 5 | Remote sub-tasks hear remote state changes between turns | A reply while following cancels the follow and starts a turn | docs/specs/issue-27/requirements.md#R3 | tests/integration/agents/test_remote_updates.py:160 |
| 6 | Remote sub-tasks hear remote state changes between turns | updates = "off" keeps today's behaviour | docs/specs/issue-27/requirements.md#R4 | tests/integration/agents/test_remote_updates.py:191 |
| 7 | Remote sub-tasks hear remote state changes between turns | The push config is deleted when the stand-in is cancelled | docs/specs/issue-27/requirements.md#R5 | tests/integration/agents/test_remote_updates.py:218 |
| 8 | Remote sub-tasks hear remote state changes between turns | A failed registration falls back to follow | docs/specs/issue-27/requirements.md#R1 | tests/integration/agents/test_remote_updates.py:244 |
| 9 | Remote sub-tasks hear remote state changes between turns | The parent's row moves and its model is told only of an ending or a new question | docs/specs/issue-27/requirements.md#R2 | tests/integration/agents/test_remote_updates.py:275 |
| 10 | Remote sub-tasks hear remote state changes between turns | A status text the redactor masks is compared as it is recorded | docs/specs/issue-27/requirements.md#R3 | tests/integration/agents/test_remote_updates.py:312 |
| 11 | Remote sub-tasks hear remote state changes between turns | A push config that cannot be deleted does not change how the stand-in ends | docs/specs/issue-27/requirements.md#R5 | tests/integration/agents/test_remote_updates.py:344 |
| 12 | Remote sub-tasks hear remote state changes between turns | A stand-in whose history passes the bound rolls over and keeps watching | docs/specs/issue-27/requirements.md#R2 | tests/integration/agents/test_remote_updates.py:372 |
| 13 | Remote sub-tasks hear remote state changes between turns | A failed fetch during the rechecks keeps the last state and the watch alive | docs/specs/issue-27/requirements.md#R2 | tests/integration/agents/test_remote_updates.py:416 |
| 14 | Remote sub-tasks hear remote state changes between turns | A push that arrives while a turn's stream is open is applied only after the turn | docs/specs/issue-27/requirements.md#R2 | tests/integration/agents/test_remote_updates.py:473 |
```
