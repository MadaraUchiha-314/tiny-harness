# Agent

The `[agent]` section names the agent. You need it when one process runs several
agents. With one agent, you can leave it out.

## Example

```toml
[agent]
id = "billing"
name = "Billing"
description = "Answers questions about invoices and payments."
```

## `[agent]` settings

| Setting | Default |
|---------|---------|
| [`id`](#id) | `"tiny-harness"` |
| [`name`](#name) | `"tiny-harness"` |
| [`description`](#description) | A short description of tiny-harness |

### `id`

The name that identifies the agent. Other agents and the tasks see this name.

- **Default:** `"tiny-harness"`
- **Values:** lowercase letters, digits and `-`. It starts with a letter or a digit. It
  has 63 characters or fewer. Any other value stops tiny-harness and names
  `agent.id`.
- **Set it when:** one process runs several agents. Each agent needs its own id. A
  second agent with the same id does not start.

The id also sets these defaults:

- The Temporal task queue: [`task_queue`](temporal#task-queue).
- The name of the timer that checks the agent's tasks: `tiny-harness-heartbeat` for the
  default id, `tiny-harness-heartbeat-<id>` for any other id.

### `name`

The agent's name in its card. A card is the public description that clients read
first.

- **Default:** `"tiny-harness"`
- **Set it when:** clients or other agents show the agent's name to people.

### `description`

The agent's description in its card.

- **Default:** a short description of tiny-harness.
- **Set it when:** other agents choose an agent from its description.
