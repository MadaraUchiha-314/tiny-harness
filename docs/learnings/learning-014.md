# Learning 014: A parent hears its sub-task late, and a rollover must not drop a pending cancel

- **Date:** 2026-10-13
- **Source:** user-feedback (the owner on PR #37: "the integration tests in `main` branch are also failing … pls fix those as well in this PR")
- **Work item:** issue-36

## What happened

Three integration tests on `main` failed sometimes in CI. All three came from one
change in issue-34: a `/sub-task` child became a real A2A task. Its parent now hears about
it later, through a stand-in workflow that reads the child's state when the child's push
arrives.

- **Tests that read the parent's view too early.** A TUI test waited on the sub-task's own
  row and then completed the parent before the parent had heard. A durable test expected
  a WORKING relay that fetch-on-push may never see.
- **A production bug that the delay exposed.** A stand-in's row update woke a parent as
  its cancel arrived. The readiness check then ran `continue_as_new`, whose snapshot
  carries no pending cancel, so the cancel was lost and the task never ended.

## Learning

- **Wait for the observer you assert on.** When a parent learns state through a stand-in,
  a test of the parent waits for the parent's own record, not for the child's.
- **A continue-as-new must carry, or wait for, every pending signal.** Before a workflow
  rolls over, check for signals its snapshot does not hold.
