# A2A extensions

tiny-harness is an [A2A 1.0](https://a2a-protocol.org/) agent. Its agent card advertises
five extensions; a client activates them with the `A2A-Extensions` header, and a request
naming an extension the card does not list is refused with the unsupported-operation
error.

| URI | What it adds |
|-----|--------------|
| [`…/a2a/ext/task/v1`](ext/task/v1) | the task attributes A2A lacks (name, goal, acceptance criteria, participants, plan, sub-task links) in `Task.metadata`, and the event envelope as data parts |
| [`…/a2a/ext/channel/v1`](ext/channel/v1) | channels between participants: messages, help requests and help replies as data parts |
| [`…/a2a/ext/status/v1`](ext/status/v1) | why a task is in `INPUT_REQUIRED`: the sub-state `awaiting-next-message` (the turn ended, the conversation is open) or `awaiting-answer` (`ask_participant`), in `Task.metadata` and the status update's metadata |
| [`…/a2a/ext/commands/v1`](ext/commands/v1) | the registered slash commands (name, description, argument hint) in the extension's `params` on the card, for clients to offer as completions |
| `https://a2ui.org/a2a-extension/a2ui/v0.9.1` | [A2UI 0.9.1](https://a2ui.org/) surfaces streamed as `application/a2ui+json` artifact parts, and user actions sent back as the same media type; only the basic catalog, no inline catalogs |

The full URIs are rooted at `https://madarauchiha-314.github.io/tiny-harness`. The JSON
schemas are committed under `docs/a2a/ext/` and the agent card is pinned by a contract
test (`tests/contract/test_agent_card.py`).

The status and commands extensions need no activation to take effect: the sub-state is
written into metadata either way, and a command runs whenever its text arrives. A client
that ignores them still sees the standard `TASK_STATE_INPUT_REQUIRED`, and A2A forbids
an extension from adding a `TaskState` value
([decision-007](../decisions/decision-007.md)).

## Completing a task

A task a participant's message started is never completed by the harness: a reply parks
it in `INPUT_REQUIRED · awaiting-next-message`. A participant completes it by sending a
message whose only part is the task extension's event envelope (media type as for every
envelope) with the kind `control`:

```json
{ "kind": "control", "action": "complete" }
```

- `action` is `complete`, the only action; an unknown action or any other field is
  refused.
- The sender (`X-Participant-Id`) must be on the task and not only a `watcher`: no
  sender is an invalid-params error, a stranger gets task-not-found, a watcher an
  unsupported-operation error, and nothing is interrupted.
- A turn in progress is cut. If a sub-task is unresolved, the completion is refused with
  a message naming it and the task parks in `INPUT_REQUIRED · awaiting-next-message`;
  otherwise the task ends `TASK_STATE_COMPLETED` ("completed by `<id>`") for every
  subscriber.
- A completion, a cancellation or a message for a task already in a terminal state is
  refused with an error naming that state.

Cancelling stays A2A's `CancelTask`, with the same watcher and terminal-state checks. In
Python, `tiny_harness.service.complete_message(task_id, participant_id=…)` builds the
message.
