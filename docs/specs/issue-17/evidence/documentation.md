# Documentation

Work item: issue-17 · testing-plan row T12 · commit `116199d`.

## Capability docs

| Doc | What changed |
|---|---|
| [configuration](../../../capabilities/configuration.md) | `temporal.mode` and `[temporal.embedded]` rules; per-command embedded behaviour; the programmatic API; SIGTERM; history row |
| [durable-execution](../../../capabilities/durable-execution.md) | `temporal_client`, `EmbeddedTemporal`: loopback-only (every port), `0600` state under a lock, private binary cache, no fallback; history row |
| [demo](../../../capabilities/demo.md) | `config.embedded.toml`, the optional config path, the embedded e2e, per-test e2e secrets; history row |
| [capabilities index](../../../capabilities/capabilities.md) | the two summaries above |

## Documentation

| Doc | What changed | Requirement |
|---|---|---|
| `README.md` | "No Temporal account?" run block beside the Cloud instructions | R7.1 |
| `docs/guide/getting-started.md` | "No Temporal account: embedded mode" | R7.1 |
| `docs/guide/deployment.md` | `[temporal]` and `[temporal.embedded]` rows, the `TEMPORAL_API_KEY` rule per mode, "Embedded Temporal is not a production deployment" | R7.2, R7.3 |
| `docs/architecture/architecture.md` | remote or embedded Temporal through `durable/temporal.py`; `process.py` | R7.2 |
| `docs/decisions/decision-005.md` | the embedded-mode decision | — |

The the-loop skill and its references are not this repository's and are unaffected.

## The docs site builds (VitePress fails on dead links)

```sh
bun run --cwd docs docs:build
```

Exit status `0` in 16.1 s.

````text
$ vitepress build .

  vitepress v1.6.4

- building client + server bundles...

(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rollupOptions.output.manualChunks to improve chunking: https://rollupjs.org/configuration-options/#output-manualchunks
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ building client + server bundles...
- rendering pages...
✓ rendering pages...
build complete in 15.75s.
````
