---
type: evidence
workItem: issue-3
---

# Final validation: tiny-harness: A tiny agent harness! (issue-3)

> The `evidence` node's proof: what is presented to the user to show the acceptance
> criteria are met. **Summarised from the executed verification** — `testing-plan.md`'s
> Verification results — and mapped onto the acceptance criteria rather than re-derived.
> Raw captures sit beside this file under `evidence/`.

Everything below ran on 2026-10-10 at the head of the stacked series (PR #15), after the
review rounds; the counts are the results table's.

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| R1 entities and registry | unit tests of the registry (PEP 440, `*`, not-found, remote protocol, override); API snapshot | `unit.md`, `contract.md` |
| R2 hooks on every operation | unit tests of the chain, `pre`/`in`/`post` replacement, abort, remote executors; integration: `activity.failed`/`activity.retried` between attempts | `unit.md`, `integration.md` (durable scenarios) |
| R3 plugins | unit tests of the loader; security tests of path escape and `${VAR}` rules; the demo plugin loaded live | `unit.md`, `security.md`, `e2e.md` |
| R4 system prompt, R5 skills | unit tests of sections, front matter, disclosure levels; the demo's `support-agent` skill loaded by `load_skill` in the e2e trace | `unit.md`, `e2e.md` |
| R6 tools through MCP | unit tests of validation and idempotency; security tests of unknown tools and schema drift; the demo's two stdio servers called live | `unit.md`, `security.md`, `e2e.md` |
| R7 remote agents | integration: delegation to a second harness tracks the remote task; security: a card requiring unsupported extensions refused | `integration.md`, `security.md` |
| R8 task, R9 plan | unit tests; task extension and intrinsic schemas pinned; plan visible in both renderers | `unit.md`, `contract.md`, `ui/axe.md` |
| R10 context window | unit tests of ordering, never-compact set, compaction record, untrusted framing; `cached_tokens` from call 2 in the live run | `unit.md`, `e2e.md` |
| R11 persistence | unit tests of the store; push tokens encrypted; retention sweep in the heartbeat scenarios | `unit.md`, `security.md`, `integration.md` |
| R12, R13 participants and channels | integration: help request → `INPUT_REQUIRED` → reply resumes; non-member refused; fail-closed assertions | `integration.md`, `security.md` |
| R14 A2A server | integration: every verb, streaming, replay after restart, unadvertised extension refused; agent card snapshot | `integration.md`, `contract.md` |
| R15 inbox and events | integration: a message to an executing task drained next iteration, `returnImmediately`, push configs, task envelopes on an existing task | `integration.md` |
| R16 heartbeat | integration: schedule, poll, snapshot, sweep | `integration.md` |
| R17 observability | integration: one span per operation with GenAI attributes; redaction tests; the live trace | `integration.md`, `security.md`, `e2e/trace.json` |
| R18 models | unit tests of both adapters, retries off, wire names; `gpt-6.1-sol` live | `unit.md`, `e2e.md` |
| R19 durable execution | integration: crash mid-activity resumes without a second LLM call, non-idempotent failure not retried, continue-as-new; live `kill -9` at two points with the activity attempt tables from Temporal history | `integration.md`, `crash-recovery.md` |
| R20 surfaces and renderers | TUI snapshots and keys; web unit, visual and axe suites; both surfaces captured live, the second-surface subscription | `ui/axe.md`, `evidence/ui/` |
| R21 configuration | unit tests of secrets and unknown keys; the demo configuration | `unit.md`, `gates.md` |
| R22 code structure and typing | pyright strict 0 errors, no `Any`; layout tests | `gates.md`, `unit.md` |
| R23 contract tests | 29 contract tests, 14 snapshots | `contract.md` |
| R24 the demo | the e2e run: plan, model, MCP tools, A2UI card with an action, a two-turn help request, COMPLETED; both renderers; crash recovery on Temporal Cloud | `e2e.md`, `crash-recovery.md`, `ui/` |
| Security considerations (abuse cases 2–9) | one negative test per case | `security.md`, `security-review.md` |

Not run: T11, the owner's manual walkthrough, closed by the approver's decision
(`manual-walkthrough.md`).
