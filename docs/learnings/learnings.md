# Learnings

Index of learnings captured while building tiny-harness, from user feedback and system
feedback. Each entry links a detailed record (`learning-<nnn>.md`).

| # | Title | Source | Date |
|---|-------|--------|------|
| [001](learning-001.md) | A fixture-only client never meets the real transport | system-feedback | 2026-10-10 |
| [002](learning-002.md) | Framework routes with root-level path parameters shadow your own | system-feedback | 2026-10-10 |
| [003](learning-003.md) | Provider tool-name constraints belong at the adapter boundary | system-feedback | 2026-10-10 |
| [004](learning-004.md) | A Temporal client interceptor is also every worker's interceptor | system-feedback | 2026-10-10 |
| [005](learning-005.md) | A browser used for visual tests must be the one CI uses | system-feedback | 2026-10-10 |
| [006](learning-006.md) | SIGTERM in an asyncio process must cancel the main task, not raise | system-feedback | 2026-10-10 |
| [007](learning-007.md) | The Temporal dev server initialises only a missing database file | system-feedback | 2026-10-10 |
| [008](learning-008.md) | VitePress parses angle brackets in a code span that wraps lines | system-feedback | 2026-10-10 |
| [009](learning-009.md) | An A2A push can outrun the agent's own task record | system-feedback | 2026-10-12 |
| [010](learning-010.md) | The A2A SDK logs request bodies and span errors where no redactor reaches | system-feedback | 2026-10-12 |
| [011](learning-011.md) | Temporal's time-skipping test server mishandles a query racing a continue-as-new | user-feedback | 2026-10-12 |
| [012](learning-012.md) | FastAPI 0.143 includes routers lazily and ignores a route class's `app` | system-feedback | 2026-10-13 |
| [013](learning-013.md) | Several agents in one process share every process-wide default | system-feedback | 2026-10-13 |
