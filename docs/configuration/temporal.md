# Temporal

[Temporal](https://temporal.io/) records each step of each task. When tiny-harness
stops in the middle of a task, the task continues from the last recorded step when
tiny-harness starts again. tiny-harness needs a Temporal server. You have two choices:

| Mode | What it is | Use it for |
|------|------------|------------|
| **embedded** | tiny-harness starts a small Temporal server on your computer, inside its own process | Your computer, development, tests |
| **remote** (the default) | tiny-harness connects to Temporal Cloud or to your own Temporal cluster | Production |

Embedded Temporal is not safe for production. See
[Deploy](../sdk/deploy#embedded-temporal-is-not-for-production).

## Examples

Embedded:

```toml
[temporal]
mode = "embedded"
```

Remote, with Temporal Cloud:

```toml
[temporal]
address = "my-namespace.abc12.tmprl.cloud:7233"
namespace = "my-namespace.abc12"
```

```sh
export TEMPORAL_API_KEY=...
```

## `[temporal]` settings

| Setting | Default | Embedded | Remote |
|---------|---------|----------|--------|
| [`mode`](#mode) | `"remote"` | `"embedded"` | `"remote"` |
| [`address`](#address) | none | not allowed | necessary |
| [`namespace`](#namespace) | `"default"` in embedded mode | optional | necessary |
| [`task_queue`](#task-queue) | the [agent id](agent#id) | optional | optional |
| [`tls`](#tls) | `true` | not allowed | optional |
| [`search_attributes`](#search-attributes) | `false` | optional | optional |

### `mode`

Chooses embedded or remote Temporal.

- **Default:** `"remote"`
- **Values:** `"embedded"` or `"remote"`. Any other value stops tiny-harness.

### `address`

The host and port of the remote Temporal server.

- **Default:** none. Necessary in remote mode. Not allowed in embedded mode.
- **Example:** `"my-namespace.abc12.tmprl.cloud:7233"`

### `namespace`

The Temporal namespace. A namespace keeps the data of one application apart from
other applications.

- **Default:** `"default"` in embedded mode. Necessary in remote mode.

### `task_queue` {#task-queue}

The name of the queue that the server and the workers share. Servers and workers find
each other with this name.

- **Default:** the agent id, [`[agent] id`](agent#id). With no `[agent]` section, this
  is `"tiny-harness"`.
- **Set it when:** two different deployments use one namespace with the same agent id.
  Give each a different queue. Two agents in one process cannot use one queue: the
  second agent does not start.

### `tls`

Encrypts the connection to remote Temporal.

- **Default:** `true`
- **Set it when:** your own Temporal cluster does not use TLS. Not allowed in embedded
  mode.

### `search_attributes` {#search-attributes}

Lets you search tasks in the Temporal web interface by conversation, state and agent.

- **Default:** `false`
- **Set it when:** you want to search tasks in Temporal. In remote mode, first register
  the attributes `A2AContextId`, `A2ATaskState` and `TinyHarnessAgent` on the
  namespace (Temporal Cloud: `tcld`). If you do not register them, every task fails.
  In embedded mode, tiny-harness registers them for you.

## `[temporal.embedded]` settings

Use these only with `mode = "embedded"`. All of them are optional.

```toml
[temporal.embedded]
persist = true
binary_path = "/usr/local/bin/temporal"
```

### `persist`

Keeps the tasks when tiny-harness stops.

- **Default:** `true`
- **Set it when:** you run tests or a short trial. With `false`, every task is lost
  when tiny-harness stops. The `tasks purge` and `schedules delete` commands then do
  not work.

### `database_path` {#database-path}

The file where embedded Temporal saves its data.

- **Default:** `temporal.sqlite3`, in the same folder as the
  [store](storage#sqlite-path).
- **Set it when:** several agents run in one process and you want them to share one
  embedded Temporal. Give each agent's file the same `database_path`. See
  [Several agents in one app](../sdk/mount#several-agents-in-one-app).

### `binary_path` {#binary-path}

The path of a Temporal CLI program that you installed yourself.

- **Default:** none. tiny-harness downloads the Temporal CLI one time.
- **Set it when:** the computer has no internet access, or you want a specific version.
  The file must exist and be executable, or tiny-harness does not start.

### `download_dir` {#download-dir}

The folder where tiny-harness keeps the downloaded Temporal CLI.

- **Default:** `~/.cache/tiny-harness/temporal`
- tiny-harness refuses a folder that another user owns or can write to.

### `port`

The port of the embedded Temporal server.

- **Default:** a free port that the operating system chooses.
