# Storage

tiny-harness saves tasks, plans and messages in a SQLite database file, the **store**.
These settings choose where the file is and how long tiny-harness keeps each kind of
data.

## Example

```toml
[store]
sqlite_path = "/var/lib/tiny-harness/tiny-harness.sqlite3"

[retention]
tasks = "P90D"
channel_messages = "P7D"
```

## `[store]` settings

### `sqlite_path` {#sqlite-path}

The path of the database file.

- **Default:** `"tiny-harness.sqlite3"`, in the folder where you start tiny-harness.
  The file that the CLI creates for you sets
  `~/.tiny-harness/tiny-harness.sqlite3`.
- Other files go in the same folder:
  - `temporal.sqlite3`: the data of embedded Temporal.
  - `plugin-data/`: the private data of each plugin.
  - `tiny-harness.log`: the log, when the TUI runs the agent in its own process.
- A new file is readable only by its owner. Keep the folder and its backups private.
  The file holds the conversations.
- Use one file for one host. The server and all workers must use the same file.

## `[retention]` settings

How long tiny-harness keeps each kind of data. Every
[`heartbeat.interval`](tuning#interval), tiny-harness deletes data that is older.

| Setting | What it keeps | Default |
|---------|---------------|---------|
| `tasks` | Tasks and their state | `"P30D"` (30 days) |
| `plans` | The agent's plans | `"P30D"` |
| `state` | Other task data | `"P30D"` |
| `channel_messages` | Messages on channels | `"P30D"` |
| `inbox_audit` | The record of each incoming message | `"P30D"` |
| `compactions` | The summaries of long conversations | `"P30D"` |
| `push_configs` | The addresses and tokens that clients gave for updates | `"P30D"` |

To delete one task now, run `tiny-harness tasks purge <task-id>`.

Temporal keeps its own copy of each task's history. Set its retention in Temporal. See
[What tiny-harness keeps](../sdk/deploy#what-tiny-harness-keeps-and-for-how-long).
