# Observability

These settings control the logs and traces of tiny-harness. A **log** is one line for
one event. A **trace** shows each step of a task and how long it took: the model calls,
the tool calls and the retries.

tiny-harness removes every secret from logs and traces.

## Example

```toml
[o11y]
log_level = "INFO"
otlp_endpoint = "https://otel.example.com"
service_name = "acme-support-agent"
```

## `[o11y]` settings

| Setting | Default |
|---------|---------|
| [`log_level`](#log-level) | `"INFO"` |
| [`otlp_endpoint`](#otlp-endpoint) | none |
| [`service_name`](#service-name) | `"tiny-harness"` |
| [`trace_file`](#trace-file) | none |
| [`langfuse_host`](#langfuse-host) | `"https://cloud.langfuse.com"` |

### `log_level` {#log-level}

The least important log level that tiny-harness writes.

- **Default:** `"INFO"`
- **Values:** `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`
- Logs are JSON lines on standard output. When the TUI runs the agent in its own
  process, the logs go to `tiny-harness.log` beside the [store](storage#sqlite-path).

### `otlp_endpoint` {#otlp-endpoint}

The address of an [OpenTelemetry](https://opentelemetry.io/) collector. tiny-harness
sends traces to it over OTLP/HTTP. Most monitoring systems accept OTLP.

- **Default:** none. tiny-harness sends no traces.

### `service_name` {#service-name}

The name of this program in your traces.

- **Default:** `"tiny-harness"`
- **Set it when:** you run more than one agent and want to tell them apart.

### `trace_file` {#trace-file}

A file where tiny-harness also writes each trace step as one JSON line.

- **Default:** none.
- **Set it when:** you want traces without a collector, for example during
  development. The file grows until you rotate it.

### `langfuse_host` {#langfuse-host}

The address of your [Langfuse](https://langfuse.com/) server.

- **Default:** `"https://cloud.langfuse.com"`
- tiny-harness sends traces to Langfuse only when you set both `LANGFUSE_PUBLIC_KEY`
  and `LANGFUSE_SECRET_KEY`.

## Health

`GET /_monitor` on the server returns the tasks that run now and their states. It
updates every [`heartbeat.interval`](tuning#interval).
