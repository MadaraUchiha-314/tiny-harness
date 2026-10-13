# Learning 011: Temporal's time-skipping test server mishandles a query racing a continue-as-new

- **Date:** 2026-10-12
- **Source:** user-feedback (a reviewer on PR #28: "Again integration test is taking 20+ mins")
- **Work item:** issue-27

## What happened

CI's integration job ran for 20+ minutes. One rollover test,
`test_a_sub_task_note_survives_a_cut_turn_and_a_rollover`, hung or failed about 1 run in
20, on `main` as well as on the branch. Its `until` helper polls the `task` query every
50 ms, and the workflow continues as new mid-test. On a bad run the worker logged
`Task not found when completing … workflow execution already completed` for the old run.
After that, either the query failed with `query deadline exceeded`, or the workflow's
tasks stopped arriving and `result()` never returned.

The failure rates:

| Configuration | Failed |
|---------------|--------|
| time-skipping test server, sticky worker | about 1 in 20 |
| time-skipping test server, non-sticky worker | 11 in 40 |
| local dev server (`start_local`) | 0 in 40 |

The job had no per-test timeout, so a hang lasted until the job limit.

## Learning

When a Temporal test hangs only sometimes and involves a continue-as-new, compare it
against `WorkflowEnvironment.start_local` before suspecting the workflow. Don't use the
time-skipping server unless a test actually skips time. Every CI test run needs a
per-test timeout, so that a hang fails fast and names its test.

## Action

The shared fixture uses `start_local`. `pytest-timeout` sets 120 s per test, and e2e
tests opt out. The switch exposed one test asserting an intermediate snapshot, which is
fixed.
