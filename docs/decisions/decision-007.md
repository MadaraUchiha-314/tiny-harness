# Decision 007: Conversations park in `INPUT_REQUIRED` with a metadata sub-state, a control envelope completes them, and commands are a hook-extensible registry

- **Status:** proposed (accepted when the issue-25 pull request is approved)
- **Date:** 2026-10-12
- **Deciders:** @MadaraUchiha-314 (approver), the-loop (proposer)
- **Work item:** [issue #25](https://github.com/MadaraUchiha-314/tiny-harness/issues/25)

## Context

Before issue #25, a reply without a tool call completed the task, and A2A forbids
restarting a terminal task, so every exchange became a new task. The ticket asked for a
task that stays open after a reply, explicit Complete and Cancel controls in both
renderers, and in-conversation controls (`/model`, `/effort`, `/sub-task`, `/status`)
that code and plugins can extend. A2A constrains the shape of the answer:

- Its `TaskState` enum is closed. Extensions "should use existing enum values and
  annotate additional semantic meaning in the `metadata` field", and the protocol's docs
  give task sub-states as the example
  ([Extensions](https://a2a-protocol.org/latest/topics/extensions/)).
- `input-required` is the interrupted state an agent uses when it needs the client.
- `TaskStatus` has no metadata field; `Task.metadata` and the status update's metadata
  do.
- A2A has `CancelTask` but no verb to complete a task.

## Decision

1. **A reply parks the task.** A task a participant's message started (lifecycle
   `conversation`) ends each turn in `TASK_STATE_INPUT_REQUIRED`. Tasks the agent
   delegates (`spawn_subtask`, participant tasks) keep completing on their own, so a
   parent can go on.
2. **The reason is a sub-state in metadata, declared by an extension.** The
   [status extension](../a2a/ext/status/v1) writes `sub_state` (`awaiting-next-message`
   or `awaiting-answer`) into `Task.metadata` and the status update's metadata, whether
   or not a client activates it. The value is an open string; an unknown value means
   plain `INPUT_REQUIRED`. Leaving `INPUT_REQUIRED` removes it.
3. **Completion is a message, not a new verb.** A participant completes a task with a
   message whose one data part is the existing event envelope with
   `{"kind": "control", "action": "complete"}`. The workflow's update validator checks
   the sender's role before anything is interrupted; the control then cuts a running
   turn and runs `decide_completion` with `requested_by`, so the unresolved-sub-task
   rule and its hook override still apply. Cancel stays A2A's `CancelTask`.
4. **Commands are a programmatic registry run through a hook operation.** A message that
   is exactly `/<name> <arguments>` for a registered name runs on the harness, never the
   model; anything else, an unregistered `/name` included, is an ordinary message. Each
   command's body is an `in` executor on `command.invoked`, filtered to its own name.
   Code registers one with `CommandRegistry.register`, a plugin with `commands.json` and
   a command-owned `hooks.json` entry (local or remote), and the four built-ins come the
   same way at the default body priority, with a built-in `pre` role policy. The
   registry is frozen before the worker starts and listed on the card by the
   [commands extension](../a2a/ext/commands/v1).

## Consequences

- An A2A client that waited for `COMPLETED` to know a reply was done must now treat any
  final status update, `INPUT_REQUIRED` included, as the end of a turn. The demo, the
  e2e tests and both renderers were changed to match.
- An extension-unaware client still works: it sees the standard state and can complete
  only by sending the envelope or cancel with `CancelTask`.
- Commands extend like every other operation: an operator can tighten the role policy,
  replace a built-in body, or serve a command from a remote executor without code in the
  harness. Policy hooks on `request.received` do not see commands or controls;
  `command.invoked` is their policy point.
- A participant can now change the model and effort (cost) and create tasks. The
  selectable-models allowlist, the watcher refusal and the existing rate limit bound it.
- A parked conversation keeps its workflow open until a participant completes or cancels
  it.

## Alternatives considered

- **A new `TaskState` value (e.g. `awaiting-next-message`).** Rejected: A2A extensions
  cannot add enum values, and every client would break on an unknown state.
- **Complete the task after each reply and continue in a new task with the same
  `contextId`.** Rejected: it is what the ticket complained about; the history, plan
  and sub-tasks would be split across tasks.
- **A custom JSON-RPC method or REST route for completion.** Rejected: no A2A client can
  call it without custom transport code; a message works over every binding and the
  official SDKs as they are.
- **Agent-initiated completion through an intrinsic tool.** Left out of scope (open
  question 3 of the requirements); only a participant ends a conversation.
- **Commands resolved in each renderer, or defined in the configuration file.**
  Rejected: renderer-side commands would differ by client, and configuration-defined
  commands could not carry a body. Resolving on the harness gives every A2A client the
  same behaviour from the same text.
- **A command registry separate from the hook system.** Rejected: plugins, remote
  executors, priorities and overrides would have to be built a second time.
