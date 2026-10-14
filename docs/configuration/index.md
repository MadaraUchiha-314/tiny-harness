# Configuration

tiny-harness reads its settings from one file in [TOML](https://toml.io/) format. This
section explains each setting. It is for CLI users and SDK users.

## Where the file is

| You use | The file is |
|---------|-------------|
| `tiny-harness` with no `--config` | `~/.tiny-harness/config.toml`. tiny-harness creates it on the first run |
| `tiny-harness --config FILE` | `FILE`. tiny-harness does not read or create `~/.tiny-harness/` |
| Python: `Settings.load(path)` | `path`. The SDK never reads `~/.tiny-harness/` |

Run `tiny-harness --help` to see which file is in use.

## Three complete examples

**On your computer, with OpenAI.** This is the file tiny-harness creates for you:

```toml
[temporal]
mode = "embedded"

[temporal.embedded]
persist = true

[openai]
model = "gpt-6.1-sol"

[server]
bind = "127.0.0.1:8080"
base_url = "http://127.0.0.1:8080"

[store]
sqlite_path = "/home/you/.tiny-harness/tiny-harness.sqlite3"
```

**On your computer, with a local model and no key:**

```toml
[temporal]
mode = "embedded"

[openai]
base_url = "http://127.0.0.1:11434/v1"
api = "chat_completions"
model = "qwen3:8b"
context_window_tokens = 16384

[server]
base_url = "http://127.0.0.1:8080"
```

**In production, with Temporal Cloud:**

```toml
plugins = ["/opt/my-agent/plugin"]

[temporal]
address = "my-namespace.abc12.tmprl.cloud:7233"
namespace = "my-namespace.abc12"

[openai]
model = "gpt-6.1-sol"
reasoning_effort = "medium"

[server]
bind = "0.0.0.0:8080"
base_url = "https://agent.example.com"

[store]
sqlite_path = "/var/lib/tiny-harness/tiny-harness.sqlite3"

[o11y]
otlp_endpoint = "https://otel.example.com"
```

## The sections

| Section | What it controls | Page |
|---------|------------------|------|
| `[agent]` | The agent's id, name and description | [Agent](agent) |
| `[temporal]`, `[temporal.embedded]` | Where tiny-harness keeps the steps of each task | [Temporal](temporal) |
| `[openai]`, `[anthropic]` | Which AI model the agent uses | [Models](models) |
| `[server]` | The address, limits and web access of the server | [Server](server) |
| `plugins`, `agents`, `[card]` | Tools, skills, other agents, and how other agents see this one | [Plugins and other agents](plugins-and-agents) |
| `[store]`, `[retention]` | Where data is saved, and for how long | [Storage](storage) |
| `[o11y]` | Logs and traces | [Observability](observability) |
| `[heartbeat]`, `[retries]`, `[context]` | Timers, retries and the size of the model's input | [Tuning](tuning) |

Two settings are always necessary:

- `[server] base_url`.
- A `[temporal]` section: `mode = "embedded"`, or the `address` and `namespace` of
  remote Temporal.

Every other setting has a default. This is the smallest complete file:

```toml
[temporal]
mode = "embedded"

[server]
base_url = "http://127.0.0.1:8080"
```

## How to write values

| Kind | Example | Notes |
|------|---------|-------|
| Text | `model = "gpt-6.1-sol"` | In double quotes |
| Number | `max_output_tokens = 2000` | No quotes |
| True or false | `persist = true` | `true` or `false`, no quotes |
| List | `plugins = ["a", "b"]` | Square brackets |
| Duration | `interval = "PT30S"` | [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601#Durations) format. `"PT30S"` is 30 seconds, `"PT2M"` is 2 minutes, `"P30D"` is 30 days. A number is a number of seconds |
| Path | `sqlite_path = "data/th.sqlite3"` | A relative path starts from the folder where you start tiny-harness |
| Web address | `base_url = "https://agent.example.com"` | Starts with `http://` or `https://` |

## Secrets

Secrets never go in the file. tiny-harness reads them from environment variables only.

| Variable | Necessary when |
|----------|----------------|
| `OPENAI_API_KEY` | You use OpenAI. Not necessary when you set `[openai] base_url`. If you set it, tiny-harness sends it to that address |
| `TEMPORAL_API_KEY` | You use remote Temporal. **Do not set it** with embedded Temporal: tiny-harness refuses to start |
| `ANTHROPIC_API_KEY` | You use Anthropic |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | You send traces to Langfuse |

Keep secrets in a password manager or a secret manager. Do not write them in a script.

tiny-harness removes every secret value from its logs, traces and saved messages.

## When a setting is wrong

tiny-harness does not start. It exits with status 2 and names the problem:

- A missing secret: the name of the variable, for example `OPENAI_API_KEY`.
- An unknown or wrong setting: the setting, for example `openai.models` or
  `temporal.mode`.

tiny-harness refuses unknown settings, so a spelling mistake never goes unseen.
