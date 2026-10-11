---
type: evidence
workItem: issue-19
---

# Documentation: Support connecting to any OpenAI-compatible API

The new `[openai]` keys, the key rule and the offline demo are described where a user
meets them first (README, getting started, deployment) and where a user checks current
behaviour (the three capability docs); the docs site builds.

## Capability docs

| Capability doc | What changed | History row |
|----------------|--------------|-------------|
| [`configuration.md`](../../../capabilities/configuration.md) | `[openai]` keys and validation (`base_url`, `api`, `context_window_tokens`), `OPENAI_API_KEY` optional with a `base_url`, the fail-closed rules | issue-19 |
| [`models.md`](../../../capabilities/models.md) | endpoint routing (no `OPENAI_BASE_URL`, no redirects, no org/project headers, keyless), the Chat Completions mapping and finish rule, parse failures as `ProviderError`, model info and endpoint observability | issue-19 |
| [`demo.md`](../../../capabilities/demo.md) | `config.ollama.toml` and the Ollama e2e with its skip rule | issue-19 |

## Documentation

| Document | What changed |
|----------|--------------|
| `README.md` | "Run the demo": any OpenAI-compatible server via `base_url` / `api`, and the offline Ollama run |
| [`guide/getting-started.md`](../../../guide/getting-started.md) | new section "No OpenAI account: any OpenAI-compatible server", with the offline prerequisites and the startup log line |
| [`guide/deployment.md`](../../../guide/deployment.md) | the `[openai]` row of the configuration reference and the `OPENAI_API_KEY` row of the secrets table |
| `examples/demo/README.md` | points to `config.embedded.toml` and `config.ollama.toml` for a run with no accounts |
| `examples/demo/config.ollama.toml` | new; its header comments are the bring-up steps |
| [`decisions/decision-006.md`](../../../decisions/decision-006.md) | new: the endpoint is configuration-only; a custom endpoint reuses `OPENAI_API_KEY` |

## Site build (T12)

```text
$ bun run --cwd docs docs:build
✓ building client + server bundles...
✓ rendering pages...
build complete in 17.25s.
```
