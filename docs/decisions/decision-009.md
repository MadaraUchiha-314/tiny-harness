# Decision 009: Several agents in one process are kept apart by task queue, refused stores and lazy peers

- **Status:** proposed (accepted when the issue-36 pull request is approved)
- **Date:** 2026-10-13
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #36](https://github.com/MadaraUchiha-314/tiny-harness/issues/36)

## Context

Issue #36 lets a developer mount agents on their own Starlette or FastAPI app, several
agents in one process, each from its own configuration. Before it, two harnesses in one
Temporal namespace shared the task queue `tiny-harness`. Each one answered `GetTask` and
`ListTasks` for the other's tasks, because a task id is the workflow id. Both wrote one
heartbeat schedule and joined their tasks as the same participant. The agents must also
reach each other inside one service, which is not listening while its lifespan starts
them.

## Decision

1. **The task queue marks ownership.**
   - `[temporal] task_queue` defaults to `[agent] id`.
   - Before an agent answers for a task id or a push, it calls `describe()` on the
     workflow and compares the queue. A foreign queue gives the same answer as an
     unknown id.
   - The answer never changes, so it is cached per id (4,096 ids).
   - `ListTasks` and the heartbeat scan filter on the built-in `TaskQueue` search
     attribute.
2. **Clashes are refused, not shared.**
   - A process-wide registry refuses a second harness with the same agent id, the same
     namespace and queue, or the same store file, before it connects.
   - Two agents never share a SQLite store, so the store fallback of a lookup only ever
     sees the agent's own records.
3. **The default agent keeps its names.** For the id `tiny-harness`, the queue, the
   heartbeat schedule id and the participant id are as before. Existing deployments
   change nothing.
4. **A peer in the same process gets a card built from its settings.** Every `Harness`
   is recorded by its public URL when it is built. A `[[agents]]` URL that names one
   gets that harness's card built from its `[card]` and its public URL, without a fetch,
   as issue-34 builds the card of `self`. A peer elsewhere is still fetched at start, so
   a wrong URL still fails fast. Calls between agents in one process go over HTTP through
   each other's routes. There is no in-process shortcut.
5. **With a participant resolver, nothing self-asserted counts.** The header is ignored,
   and a message's own `participant_id` claim cannot stand in for a missing resolved
   participant.

## Alternatives considered

- **Prefix every workflow id with the agent id.** This gives structural isolation with no
  extra RPC. It was rejected because it changes every handle lookup (workflows,
  activities, the event bridge, the push receiver) and breaks the running workflows of
  existing deployments.
- **An agent column in every store record.** This is a migration of every record kind
  for a configuration that one store file per agent already serves.
- **An in-process transport between co-hosted agents.** It is faster, but it would skip
  the routes, the middleware and the access checks that protect an agent from its
  peers.
- **Fetching a same-process peer's card on first use.** The first version did this. It
  gave the issue-34 roster a placeholder card with no description, and it also deferred
  a sibling service behind the same gateway origin.
- **Retrying a peer's card fetch at start until the service listens.** The service starts
  listening only after every lifespan has finished, so this would wait forever.

## Consequences

- A lookup of a new task id costs one more Temporal RPC per process.
- A same-process peer's built card has no registered commands in it. The roster does
  not use them.
- Two processes can still be given one agent id. The registry sees one process only, and
  the deploy guide says so.
