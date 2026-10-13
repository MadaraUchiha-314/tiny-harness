# Tuning

The defaults on this page work for most agents. Change them only when you have a
reason.

## `[heartbeat]`

### `interval`

How often tiny-harness does its background work: it checks channels for new messages,
updates `GET /_monitor` and deletes data that is older than the
[retention](storage#retention-settings) settings.

- **Default:** `"PT30S"` (30 seconds)

## `[retries]`

What tiny-harness does when a step fails, for example when the model server is busy.
tiny-harness waits, then tries again. Each wait is longer than the last, until a
maximum.

```toml
[retries.default]
initial_interval = "PT1S"
backoff_coefficient = 2.0
maximum_interval = "PT60S"
maximum_attempts = 5

[retries.per_activity.invoke_llm]
maximum_attempts = 10
```

| Setting | Default | What it does |
|---------|---------|--------------|
| `initial_interval` | `"PT1S"` | The wait before the second attempt |
| `backoff_coefficient` | `2.0` | Each wait is the last wait times this number |
| `maximum_interval` | `"PT60S"` | The longest wait |
| `maximum_attempts` | `5` | The number of attempts, the first one included |
| `non_retryable_error_types` | none | Error types that tiny-harness never retries |

`[retries.default]` applies to every step. `[retries.per_activity.<step>]` changes one
step. The steps you will most often change are `invoke_llm` (a model call) and
`invoke_tool` (a tool call).

tiny-harness never retries a tool that can change data, unless its MCP server marks
it as idempotent or read-only.

## `[context]`

The **context** is all the text tiny-harness sends to the model in one request: the
instructions, the conversation and the tool results. It is measured in tokens. A token
is about four characters of English.

| Setting | Default | What it does |
|---------|---------|--------------|
| `turn_budget_tokens` | `12000` | The largest context tiny-harness sends. The real limit is this value or the model's [`context_window_tokens`](models#context-window-tokens), whichever is smaller |
| `compaction_fraction` | `0.75` | When the context is larger than this part of the limit, tiny-harness writes a summary of the older conversation |
| `history_event_bound` | `10000` | When one task records this many events in Temporal, tiny-harness continues the task in a new, empty history. The conversation stays the same |

Increase `turn_budget_tokens` when the agent forgets the start of a long conversation
too soon, and the model's window is larger.
