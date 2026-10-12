# Capability: tasks-and-plans

> Every unit of work is an A2A task extended with a goal, acceptance criteria,
> participants and sub-task links, and a plan of steps the participants can read.

## What it is

The shared record of what is being done and for whom. The A2A task is the task; what A2A
lacks lives in its metadata under the task extension, and the core loop runs the ticket's
five lines over it. Lives in `tiny_harness/harness/core/`.

## Current behaviour

- A task SHALL be an `a2a.types.Task` whose metadata key
  `io.github.madarauchiha-314.tiny-harness/task` holds the extension data: name,
  optional type, goal, description, acceptance criteria, participants (each with a role
  from `assignee`, `reporter`, `watcher`, `admin`), parent and sub-task links, and the
  plan, plus three server-controlled fields: `lifecycle` (`conversation` or
  `delegated`), `model` and `reasoning_effort`. A `task` envelope that carries any of the
  three SHALL be refused whole, from any participant, admins included. A task persisted
  without `lifecycle` reads as `delegated` when it has a parent and `conversation`
  otherwise. The A2A state in `Task.status.state` SHALL be the authoritative state.
- The extension SHALL be advertised in the agent card under
  `https://madarauchiha-314.github.io/tiny-harness/a2a/ext/task/v1` and its schema
  published under `docs/a2a/ext/task.json`.
- A plan SHALL be a directed acyclic graph of steps, each with a name, description,
  optional output and `linked_tasks`; a plan with a cycle SHALL be rejected with a typed
  error. `create_plan` attaches it through the `plan.created` operation, `complete_step`
  records a step's output, and the plan is persisted on every change.
- WHEN `spawn_subtask` runs THEN a sub-task SHALL be created, linked from the current
  step and recorded in the parent's sub-task list; a local sub-task runs as a child
  workflow and a remote one as a remote task workflow, and the parent SHALL NOT complete
  while a sub-task is unresolved unless a hook overrides the rule.
- The core loop SHALL be: assemble the context (compacting first if over budget), invoke
  the model, extract the tool calls, stop when there are none (then run the completion
  predicate, or park a conversation), otherwise execute each call through the validating
  invoker. An intrinsic's command is applied in the loop with no I/O.
- WHEN a `conversation` task's turn ends without a tool call THEN it SHALL park in
  `INPUT_REQUIRED` with the status sub-state `awaiting-next-message`, never
  `COMPLETED`; a `delegated` task (an agent's `spawn_subtask`, a participant task)
  still runs the completion predicate. `ask_participant` parks the task with
  `awaiting-answer`. The next message resumes it in `WORKING` and clears the sub-state,
  which lives in `Task.metadata` under the [status extension](../a2a/ext/status/v1) key,
  so the event log, the store and `GetTask` carry it. A refused message does not wake a
  parked task, and a conversation started with no message parks without a model call.
- A participant SHALL end a conversation by completing it (the `control` envelope) or
  cancelling it; `decide_completion` then runs with `requested_by`, a turn in progress is
  cut, and an unresolved sub-task refuses the completion (the task parks again) unless a
  hook overrides the rule.
- `/sub-task <description>` SHALL create a `conversation` child in the same `contextId`,
  with the sender as reporter, the agent as assignee and the description as goal; it
  starts parked. Every local child, from `spawn_subtask` or `/sub-task`, inherits the
  parent's `model` and `reasoning_effort`. A participant's `/sub-task` notes the child
  in the parent's history without waking it; the child's completion wakes the parent as
  any sub-task's does.
- A local sub-task SHALL signal its parent on every state change. The parent records the
  child's `state` and `sub_state` on its `sub_tasks` entry and, once idle (no message
  waiting on an answer), emits the updated `Task` on its own stream, so a client
  following the parent sees each row change. Only an ending, or a remote child's turn,
  becomes a note for the parent's model; a child parking or resuming never wakes it.
- WHEN a task reaches a terminal state THEN the matching status update SHALL be emitted
  to every subscriber and the final state persisted before the workflow returns.
- The plan SHALL be readable through the extension and rendered by both renderers.

## Design

[issue-25 design § Task lifecycle](../specs/issue-25/design.md#task-lifecycle),

[design.md § Core: task, plan, state](../specs/issue-3/design.md#core-task-plan-state-r8-r9--harnesscore),
[design.md § The core loop](../specs/issue-3/design.md#the-core-loop),
[decision-004](../decisions/decision-004.md).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Task extension, plan, state, intrinsic bodies and the core loop (Layer 4); child and remote task workflows (Layer 5) | [spec](../specs/issue-3/), [PR #10](https://github.com/MadaraUchiha-314/tiny-harness/pull/10), [PR #11](https://github.com/MadaraUchiha-314/tiny-harness/pull/11), [decision-004](../decisions/decision-004.md) |
| issue-25 | Conversation tasks park in `INPUT_REQUIRED` (`awaiting-next-message` / `awaiting-answer`) instead of completing; participant completion; `lifecycle`, `model`, `reasoning_effort` as server-controlled fields; `/sub-task` children and settings inheritance | [spec](../specs/issue-25/), [PR #26](https://github.com/MadaraUchiha-314/tiny-harness/pull/26), [decision-007](../decisions/decision-007.md) |
