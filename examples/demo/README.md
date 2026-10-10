# tiny-harness demo

One harness instance, two surfaces, one task: "Refund order #48213: the customer says the
blender arrived cracked. Check the order and propose a resolution."

```bash
export TEMPORAL_API_KEY="$(secret-tool lookup service temporal project tiny-harness)"
export OPENAI_API_KEY="$(secret-tool lookup service openai project tiny-harness)"
export TINY_HARNESS_PUSH_KEY="$(openssl rand -base64 32)"
bun install --cwd renderers/web && bun run --cwd renderers/web build
uv run python -m examples.demo          # server + worker, web renderer at /ui
uv run tiny-harness tui --url http://127.0.0.1:8080
```

The plugin in this directory registers two stdio MCP servers (`orders`, `policy`), the
`support-agent` skill and a prompt extension. `tests/e2e/test_demo.py` drives the same
task through the A2A client; `tests/e2e/test_crash_recovery.py` kills the worker at two
points and checks the task completes without a duplicated LLM or tool call.
