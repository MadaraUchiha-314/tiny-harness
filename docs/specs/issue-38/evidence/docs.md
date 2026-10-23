# T15 — docs build

Work item issue-38, activity T15. The VitePress site builds with the new and changed
pages, including this work item's spec chain and evidence.

2026-10-22, branch `issue-38-multimodal` at `22701e9` plus the uncommitted evidence and
the filled `testing-plan.md` (the content committed with this file).

## `cd docs && bun run docs:build`

```text
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
build complete in 24.61s.
exit=0
```

The chunk-size note is the existing Mermaid bundle warning.

## The new and changed pages built

Every page below exists in `docs/.vitepress/dist` after the build. Markdown lint for the
same pages is the `markdownlint` hook in T13.

| Page | Source | Built |
|------|--------|-------|
| Images and voice | `docs/configuration/media.md` | yes (74 KiB) |
| Use the TUI | `docs/cli/tui.md` | yes (71 KiB) |
| CLI quickstart | `docs/cli/index.md` | yes (62 KiB) |
| Example: images and voice | `docs/sdk/example-multimodal.md` | yes (70 KiB) |
| Add tools, commands and skills | `docs/sdk/extend.md` | yes (92 KiB) |
| SDK quickstart | `docs/sdk/index.md` | yes (82 KiB) |
| Media extension v1 | `docs/a2a/ext/media/v1.md` | yes (112 KiB) |
| Commands extension v1 | `docs/a2a/ext/commands/v1.md` | yes (75 KiB) |
| A2A extensions | `docs/a2a/extensions.md` | yes (61 KiB) |
| Capability: media | `docs/capabilities/media.md` | yes (153 KiB) |
| Capability: surfaces-and-renderers | `docs/capabilities/surfaces-and-renderers.md` | yes (159 KiB) |
| Capability: models | `docs/capabilities/models.md` | yes (157 KiB) |
| Capability: configuration | `docs/capabilities/configuration.md` | yes (161 KiB) |
| Configuration | `docs/configuration/index.md` | yes (71 KiB) |
| Models | `docs/configuration/models.md` | yes (69 KiB) |
| Storage | `docs/configuration/storage.md` | yes (60 KiB) |
| Decision 010: Media by reference: bytes in one task-scoped store | `docs/decisions/decision-010.md` | yes (151 KiB) |
| Architecture — tiny-harness | `docs/architecture/architecture.md` | yes (153 KiB) |

274 HTML pages in total; the build exited 0 with no dead-link errors.
