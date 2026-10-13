# Server

The server receives messages from clients: the TUI, the web renderer, your code and
other agents. These settings control where it listens and what it accepts.

## Example

```toml
[server]
bind = "0.0.0.0:8080"
base_url = "https://agent.example.com"
cors_origins = ["https://app.example.com"]
```

## `[server]` settings

| Setting | Default |
|---------|---------|
| [`base_url`](#base-url) | none: you must set it |
| [`bind`](#bind) | `"127.0.0.1:8080"` |
| [`cors_origins`](#cors-origins) | none |
| [`ui_dir`](#ui-dir) | none |
| [`max_request_bytes`](#max-request-bytes) | `1048576` (1 MiB) |
| [`rate_limit_per_minute`](#rate-limit-per-minute) | `120` |
| [`bridge_interval`](#bridge-interval) | `"PT0.25S"` (250 milliseconds) |
| [`delegators`](#delegators) | none |

### `base_url` {#base-url}

The address that clients use to reach the server. The server puts it in its agent
card, the public description that clients read first.

- **Default:** none. You must set it.
- **Example:** `"https://agent.example.com"` behind a gateway, or
  `"http://127.0.0.1:8080"` on your computer.
- Other agents send updates to this address. If they cannot reach it, set
  [`updates = "follow"`](plugins-and-agents#updates) for those agents.

### `bind`

The network address and port where the server listens.

- **Default:** `"127.0.0.1:8080"`. Only programs on the same computer can connect.
- **Set it when:** the server runs in a container or behind a gateway on another
  host. `"0.0.0.0:8080"` listens on all networks. Then a gateway must protect it. See
  [Deploy](../sdk/deploy#put-a-gateway-in-front).

### `cors_origins` {#cors-origins}

The websites whose web pages can connect to the server from a browser.

- **Default:** none. A web page from another website cannot connect.
- **Set it when:** you use a web renderer from another website. For the web renderer
  on this documentation site, add `"https://madarauchiha-314.github.io"`.
- **Example:** `cors_origins = ["https://app.example.com"]`

### `ui_dir` {#ui-dir}

A folder with a built web renderer. The server shows it at `/ui/`.

- **Default:** none.
- **Example:** `ui_dir = "renderers/web/dist"` in a copy of the repository.

### `max_request_bytes` {#max-request-bytes}

The largest request the server accepts, in bytes. A larger request gets the error 413.

- **Default:** `1048576` (1 MiB)

### `rate_limit_per_minute` {#rate-limit-per-minute}

The number of requests one client can send in one minute. More requests get the error
429.

- **Default:** `120`

### `bridge_interval` {#bridge-interval}

How often the server checks Temporal for new events to stream to clients.

- **Default:** `"PT0.25S"` (250 milliseconds)
- **Set it when:** you want faster updates (a smaller value) or less load on Temporal
  (a larger value).

### `delegators`

The other agents that can give this agent a full task. A full task sets how the task
ends and which model it uses.

- **Default:** none. Only this agent itself can give itself a full task. It does this
  when it runs a step in a sub-task on itself.
- **Set it when:** another tiny-harness agent gives work to this one, and you trust it.
  Then its sub-tasks end by themselves when they are done. Without it, the other agent
  still gives work to this one, but its sub-tasks stay open after they answer.
- **Example:** `delegators = ["front-desk"]`. Use the participant id that the other
  agent sends.
- Any other sender that tries to set these values gets an error, and tiny-harness does
  not create the task.
