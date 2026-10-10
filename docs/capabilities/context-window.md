# Capability: context-window

> Every model context is assembled from templated positions ordered for prefix caching,
> and compacted on a declared, replaceable policy before the call.

## What it is

The core component that decides what the model sees and what it costs. Agent state is
typed; the window is assembled from sections grouped by stability; compaction runs as
three `in` hook points. Lives in `tiny_harness/harness/core/context.py`,
`state.py` and `compaction.py`.

## Current behaviour

- Agent state SHALL be the typed `AgentState`: the conversation history (each entry an
  input item with an id), the running summary, the loaded skills, the last usage and
  `data`, a JSON object whose named subsets a plugin may describe with a JSON schema. A
  write to a described subset SHALL be validated before it is accepted.
- The context SHALL be assembled in a declared order: the static sections (system
  prompt, participant roles, skills index) go in the provider's `instructions` and,
  with the tool definitions sent as the request's tool list, form the cached prefix;
  the per-task sections (task, plan) and the per-turn sections (state summary, history,
  tool results) go in the input.
- For OpenAI, `prompt_cache_key` SHALL be the task id and the request SHALL be
  `store=false`; the usage of every call SHALL record cached tokens.
- Tool results and other untrusted content SHALL be rendered inside a delimited block
  with a fixed preamble that they are data, never instructions.
- `compaction.trigger.in` SHALL decide whether the window is over budget (default: the
  configured fraction of the smaller of the model window and the turn budget);
  `compaction.keep.in` SHALL name what survives (default: the system prompt, the task's
  goal and acceptance criteria, the current plan and every loaded skill's body);
  `compaction.summarise.in` SHALL replace the oldest half of the history with a summary
  (default: a model call). Each is replaceable by a plugin executor that sets `result`.
- WHEN compaction runs THEN a `CompactionRecord` naming what was removed and the summary
  that replaced it SHALL be persisted.
- The budget and fraction SHALL be configuration (`[context]`: `turn_budget_tokens`,
  `compaction_fraction`).

## Design

[design.md § Context window manager and compaction](../specs/issue-3/design.md#context-window-manager-and-compaction-r10--harnesscorecontextpy).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | Agent state, the context window manager, compaction (Layer 4) | [spec](../specs/issue-3/), [PR #10](https://github.com/MadaraUchiha-314/tiny-harness/pull/10) |
