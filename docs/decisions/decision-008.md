# Decision 008: A remote push is a doorbell, verified in a workflow update, and its token is kept only as a digest

- **Status:** proposed (accepted when the issue-27 pull request is approved)
- **Date:** 2026-10-12
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #27](https://github.com/MadaraUchiha-314/tiny-harness/issues/27)

## Context

Issue #27 makes a delegated remote sub-task's stand-in hear the remote task change while
it is parked. A2A gives two mechanisms:

- **Push notifications.** The client registers a URL and a token. The agent POSTs a
  `StreamResponse` with the token in `X-A2A-Notification-Token`.
- **`SubscribeToTask`.** The client holds a stream open.

Push needs an inbound endpoint, which is new attack surface on a server that has no
authentication of its own (decision-003). The token is a bearer credential. Temporal
records every activity input and result in workflow history, and the issue requires that
the token is never persisted in clear text.

## Decision

1. **The push is a doorbell.** A verified push only wakes the stand-in. The stand-in
   then fetches the task with `GetTask` from the agent in its registry, and records that
   state, never the body's. The body's claimed state decides only whether to fetch
   again: up to three times, after 1, 2 and 4 s, while the fetch disagrees. That covers
   a remote that pushes before its own `GetTask` shows the change.
2. **Verification is a Temporal update validator.**
   - The endpoint hashes the presented token.
   - It sends a `remote_push` update to the workflow its path names.
   - The validator compares the digests with `hmac.compare_digest` and checks the remote
     task id, the watch mode and that the stand-in is still open.
   - A rejected update records no update and runs no activity, and the endpoint answers
     every refusal with one `401`.
3. **Only the digest is kept.** The token is generated inside the activity that
   registers it, `register_remote_push`. It goes to the remote agent and nowhere else:
   not workflow history, not the store, not logs. Exported traces are covered too, since
   spans started during registration are never exported.
4. **Follow is the fallback, chosen per agent.** `updates = "auto" | "follow" | "off"`.
   `auto` uses push when the card advertises it and the server has a base URL.

## Consequences

- A leaked token can cost at most four `GetTask` calls per push, within the rate limit;
  it cannot change state.
- Each push costs one round trip to the remote agent.
- Rejected pushes can still leave empty workflow tasks on Temporal versions without
  speculative workflow tasks. The test server is one of them.
- Response timing may differ between an unknown task id and a wrong token. Task ids are
  not secret.

## Alternatives considered

- **Apply the push body.** It is cheaper, but it trusts the token holder with state and
  is exposed to out-of-order delivery. A stale `WORKING` push could roll a row back.
- **Query the digest, then signal.** That takes two RPCs and is not atomic. A signal is
  always recorded, so a flood of bad pushes would grow history.
- **Encrypt the token at rest.** That needs key management, which issue-23 removed. The
  digest makes it unnecessary.
