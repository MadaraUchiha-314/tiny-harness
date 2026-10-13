# tiny-harness delegation example

Two tiny-harness agents. The front desk gives order questions to the ledger by itself:
it reads the ledger's agent card, which `[card]` in `ledger.toml` describes.

```bash
unset TEMPORAL_API_KEY
export OPENAI_API_KEY="$(secret-tool lookup service openai project tiny-harness)"
uv run tiny-harness --config examples/delegation/ledger.toml serve      # port 8091, first
uv run tiny-harness --config examples/delegation/front-desk.toml serve  # port 8090
uv run tiny-harness tui --url http://127.0.0.1:8090
```

Then send "What is the status of order 48213?". The guide is
[Example: two agents](../../docs/sdk/example-delegation.md).
