# Learning 009: An A2A push can outrun the agent's own task record

- **Date:** 2026-10-12
- **Source:** system-feedback
- **Work item:** issue-27

## What happened

The stand-in treats a push as a doorbell and fetches the task with `GetTask`. Under
test, a tiny-harness remote sent its `CANCELED` push from the `emit_event` activity
before its own `GetTask` showed `CANCELED`. The stand-in fetched, saw `INPUT_REQUIRED`
and waited for good. The test passed alone and failed about one run in three.

## Learning

When an event triggers a read of the source of truth, the read can lag the event. Re-read,
on a bounded schedule, while the read disagrees with what the event claimed. The claim is
safe to use as a hint even when it is not trusted.

A related trap from the same work: a tiny-harness peer answers a task-scoped call only
for an asserted participant (decision-003). A client that omits `X-Participant-Id` on a
follow-up call gets "task not found", which looks like a missing task, not a refusal.

## Action

The stand-in rechecks after 1, 2 and 4 s (issue-27 R2.9). Every remote task call asserts
`X-Participant-Id` (R1.6).
