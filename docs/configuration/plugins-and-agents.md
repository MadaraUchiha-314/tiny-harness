# Plugins and other agents

These two settings are at the top of the file, before the first `[section]`.

```toml
plugins = ["plugins/acme-support"]
agents = [
  { id = "billing", url = "https://billing-agent.example.com" },
]

[temporal]
# ...
```

## `plugins`

The plugin folders to load. A plugin gives the agent tools, skills, prompts, hooks and
commands. [Add tools, commands and skills](../sdk/extend) explains how to make one.

- **Default:** none. The agent has no tools.
- **Example:** `plugins = ["plugins/acme-support", "/opt/shared/plugins/crm"]`
- Relative paths start from the folder where you start tiny-harness.
- If a plugin is not valid, tiny-harness does not load it. If one part of a plugin is
  not valid, tiny-harness skips that part and loads the rest.

## `agents`

Other A2A agents that this agent can give work to. The agent sends them a sub-task and
waits for the result.

- **Default:** none.
- tiny-harness reads the agent card of each agent at start. It refuses an agent that
  asks for authentication or for a protocol extension that tiny-harness does not know.

Each agent has these settings:

| Setting | Default | What it does |
|---------|---------|--------------|
| `id` | none: you must set it | The name the agent uses for this other agent |
| `url` | none: you must set it | The address of the other agent |
| `version` | none | The version that tiny-harness records for the other agent |
| [`updates`](#updates) | `"auto"` | How tiny-harness learns about changes in a waiting sub-task |
| `follow_interval` | `"PT5S"` (5 seconds) | With `follow`: the pause before tiny-harness listens again. At least 1 second |

### `updates`

A sub-task on another agent can wait for input. While it waits, it can change: for
example, a person answers it on the other agent. This setting chooses how tiny-harness
learns about the change.

| Value | What happens | Use it when |
|-------|--------------|-------------|
| `"auto"` | The other agent sends updates to this server. If the other agent cannot send updates, tiny-harness uses `"follow"` | The other agent can reach this server's [`base_url`](server#base-url) |
| `"follow"` | tiny-harness keeps a connection open to the other agent and listens | The other agent cannot reach this server |
| `"off"` | tiny-harness learns about a change only at its next message | You do not need updates between messages |

```toml
agents = [
  { id = "billing", url = "https://billing.example.com", updates = "follow", follow_interval = "PT10S" },
]
```
