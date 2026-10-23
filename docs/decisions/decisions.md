# Decision Log

Index of architecture and process decisions for tiny-harness. Each entry links a
detailed record (`decision-<nnn>.md`). Newest first.

| # | Title | Status | Date |
|---|-------|--------|------|
| [010](decision-010.md) | Media by reference: bytes in one task-scoped store | proposed | 2026-10-22 |
| [009](decision-009.md) | Several agents in one process are kept apart by task queue, refused stores and lazy peers | proposed | 2026-10-13 |
| [008](decision-008.md) | A remote push is a doorbell, verified in a workflow update, and its token is kept only as a digest | proposed | 2026-10-12 |
| [007](decision-007.md) | Conversations park in `INPUT_REQUIRED` with a metadata sub-state, a control envelope completes them, and commands are a hook-extensible registry | proposed | 2026-10-12 |
| [006](decision-006.md) | The model endpoint is configuration-only, and a custom endpoint reuses `OPENAI_API_KEY` | proposed | 2026-10-10 |
| [005](decision-005.md) | Embedded mode runs the SDK's Temporal dev server as an owned child process | proposed | 2026-10-10 |
| [004](decision-004.md) | Harness intrinsics are tools, so the core loop stays five lines | proposed | 2026-10-09 |
| [003](decision-003.md) | No authentication inside tiny-harness in the first release | proposed | 2026-10-09 |
| [002](decision-002.md) | Temporal owns the whole request lifecycle | proposed | 2026-10-09 |
| [001](decision-001.md) | Python toolchain and one definition of the checks | proposed | 2026-10-08 |
