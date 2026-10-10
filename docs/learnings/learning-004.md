# Learning 004: A Temporal client interceptor is also every worker's interceptor

- **Date:** 2026-10-10
- **Source:** system-feedback
- **Work item:** issue-3

## What happened

`build_worker` passed `TracingInterceptor()` and `connect()` also gave it to the
client. Temporal prepends client interceptors that implement the worker interface to
every worker built on that client, so each activity produced two `StartActivity` and
two `RunActivity` spans. The trace looked plausible until the demo's trace was counted
against the activity history.

## Learning

Register a Temporal interceptor in exactly one place; when the client carries it,
the worker must not add another. Count spans against the authoritative record
(Temporal history) in at least one test.

## Action

`build_worker` adds the interceptor only when the client has none;
`tests/integration/o11y` asserts one `RunActivity:invoke_llm` span per LLM step.
