---
type: evidence
workItem: issue-36
---

# Security review: mount tiny-harness agents onto an existing FastAPI or Starlette app

> The `security-review` node's proof. See `reference/security.md`.

## Security review (gate)

- **Mechanism:** the built-in `security-review` skill. A sub-task reviewed
  `git diff origin/main...HEAD -- tiny_harness examples pyproject.toml` against the
  requirements' Security considerations. It traced every A2A operation from the HTTP
  route to the Temporal call, and checked the a2a-sdk's `DefaultRequestHandler` and
  FastAPI helper. The false-positive step had nothing to filter, because no candidate
  was raised.
- **Outcome:** pass. No vulnerability at confidence 8 or higher.
- **What was checked:**
  - **Cross-agent access.** Every task operation of agent A on agent B's task: GetTask,
    CancelTask, SubscribeToTask, the four push-config operations, SendMessage with an
    existing id (the update-with-start path), the control path, ListTasks, the push
    route and the monitor.
  - **Participant-resolver bypass.** The header, message metadata, task and control
    envelopes, commands and the FastAPI path.
  - **Query injection, secrets and the router.** Visibility-query injection, secrets
    in cards, logs and errors, the FastAPI dependencies, the mount check, and the local
    peer cards with `Claims`.
- **Findings:** none at the reporting bar. One item below it, acted on in the docs:

| Item | Disposition |
|------|-------------|
| A participant resolver that returns an agent's id for a person gives that person delegator trust (issue-34's `[server] delegators` includes the agent itself), so they can set server-controlled fields of a new task | Documented in `docs/sdk/mount.md` § Use your own login: never return an agent id for a person. The rule predates this PR; whether it applies depends on how the host names its users |
| `_Limits` skips the size check for a non-numeric `Content-Length` | Excluded (resource exhaustion). The ASGI server still bounds the body |

- **Earlier security-relevant fixes from the review rounds:** a failing resolver no
  longer leaks its text (self-review 1, #4); unsafe `ListTasks` context ids are refused
  before the query (self-review 1, #3, round 2, #4); the namespace is in the claim
  (self-review 1, #2); exact mount checks (self-review 1, #6, round 2, #1).
- **Negative tests (abuse cases 1–6):** [security.md](security.md), and the new tests from
  the review rounds.
- **Effective risk tier: 4.** Inferred 3, raised because the change touches a fixed
  sensitive path (`tests/contract/snapshots/settings.schema.json`) and an identity
  boundary (the participant resolver).
- **Human sign-off:** **required (tier 4). Requested on PR #37, pending.**
