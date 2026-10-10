# Capability: participants-and-channels

> Participants with roles, channels between them and the harness, and help requests
> that put a task in `INPUT_REQUIRED` and resume it on the reply.

## What it is

How the harness asks and is answered. A channel is a set of participants the harness
manages; the default medium is A2A itself. When the agent needs one message's worth of
input it asks on a channel; when it needs real work it creates a task for the
participant. Lives in `tiny_harness/harness/channels/` and the channel extension of
`tiny_harness/service/channels.py`.

## Current behaviour

- Every participant's role SHALL be in the system prompt by default, in the overridable
  `participants` section.
- A channel SHALL be an entity (a set of participants) with send and receive for both
  the harness and the participants. The default `A2AChannel` turns a send into an A2A
  message event on the task carrying a data part of
  `application/vnd.tiny-harness.channel+json` (kinds `message`, `help_request`,
  `help_reply`), persisted before delivery; a participant sends by `SendMessage` on the
  task. The extension is advertised under
  `https://madarauchiha-314.github.io/tiny-harness/a2a/ext/channel/v1`.
- WHEN a message arrives from a participant who is not a member THEN it SHALL be
  refused with the same error whether or not the channel exists, and the refusal
  recorded; over A2A the refusal is a status update whose message says why, so the
  sender's stream ends.
- WHEN the agent calls `ask_participant` THEN the question SHALL be sent on the channel
  and the task moved to `INPUT_REQUIRED`, with the question as the status message; WHEN
  the reply arrives THEN the task SHALL resume with the reply in context and leave
  `INPUT_REQUIRED`. A waiting task survives a process restart and consumes no worker.
- WHEN the agent calls `create_task_for_participant` THEN a task assigned to that
  participant SHALL be created and linked as a sub-task.
- The choice between asking and creating a task SHALL be the `help.decided` operation:
  the default body asks the LLM for a structured decision, validates it, and re-runs
  once with the objection on failure; an executor can replace it.
- `set_participant_role` SHALL require the asserted actor to be an admin of the task;
  participant identity in message metadata is self-asserted (decision-003).
- A message that asserts no participant SHALL be refused at the executor and at intake,
  and a task operation with no `X-Participant-Id` SHALL answer not found (fail closed);
  the harness asserts itself as the sender when it delegates to a child or remote task.
- Sub-task and remote-agent results and an agent participant's messages SHALL enter the
  context inside the delimited untrusted block; a human participant's own message is the
  task's instruction.

## Design

[design.md § Participants and channels](../specs/issue-3/design.md#participants-and-channels-r12-r13--harnesschannels),
[decision-003](../decisions/decision-003.md).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Channel models, help decision, membership boundary (Layer 4); help requests over A2A and the channel extension (Layer 5) | [spec](../specs/issue-3/), [PR #10](https://github.com/MadaraUchiha-314/tiny-harness/pull/10), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11) |
