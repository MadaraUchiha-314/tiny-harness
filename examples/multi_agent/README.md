# Five agents in one app

This example runs five tiny-harness agents in one Python process and one web app. Each
agent has its own configuration file, its own path and its own task queue. Agent `a`
can delegate work to agents `b` and `c`, and agent `b` can delegate to agent `d`.

| Agent | Path | Delegates to |
|-------|------|--------------|
| `a` Front desk | `/agents/a` | `b`, `c` |
| `b` Billing | `/agents/b` | `d` |
| `c` Shipping | `/agents/c` | none |
| `d` Ledger | `/agents/d` | none |
| `e` Reports | `/agents/e` | none |

All five agents use one embedded Temporal server. They share it because their
configuration files set the same `[temporal.embedded] database_path`.

## Run it with Starlette

1. Set your model key. Embedded Temporal does not use a Temporal key, so remove it if
   it is set:

   ```sh
   export OPENAI_API_KEY=sk-...
   unset TEMPORAL_API_KEY
   ```

2. Start the app from the repository root:

   ```sh
   uv run python -m examples.multi_agent.app
   ```

3. In a second terminal, talk to agent `a`:

   ```sh
   uv run tiny-harness tui --url http://127.0.0.1:8090/agents/a
   ```

Ask agent `a` a billing question. Agent `a` sends a sub-task to agent `b` over HTTP,
through the same app.

## Run it with FastAPI

```sh
uv run python -m examples.multi_agent.app_fastapi
```

Open <http://127.0.0.1:8090/docs>. The page shows one group of routes for each agent.

## How it works

- `app.py` makes one `Harness` for each configuration file and mounts its `asgi_app()`
  at the path of the agent's `base_url`. `harnesses_lifespan` starts the five agents
  when the app starts, and stops them when the app stops.
- `app_fastapi.py` includes one `harness_router(harness)` for each agent.
- An agent finds another agent through its `[[agents]]` table. The URL points into the
  same app, so the agent builds the card of the other agent from its configuration. It
  does not fetch the card, because the app does not listen yet while it starts.

See [Mount agents on your app](../../docs/sdk/mount.md) for the full guide.
