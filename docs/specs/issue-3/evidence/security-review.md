---
type: evidence
workItem: issue-3
---

# Security review: tiny-harness: A tiny agent harness! (issue-3)

> The `security-review` node's proof. Required before ready-to-ship unless an authorized
> human declared the phase away at `phase-selection`. See `reference/security.md`.

## Security review (gate)

- **Mechanism:** the-loop checklist (`reference/security.md` § The checklist), verified
  against the diff of the stacked series (`main..loop/issue-3-l9-demo`) on 2026-10-10,
  after the two self-review rounds and the codex critic round, whose eight findings were
  security findings (abuse cases 2, 4 and 6; R15.5; R19.3) and are fixed one commit each
  (`evidence/critic-review.md`).
- **Outcome:** pass, with one residual risk recorded below for the owner.
- **Findings:** none open. The findings the reviews raised and their fixes are in
  `evidence/self-review.md` and `evidence/critic-review.md`.
- **Effective risk tier:** 4. No `riskTier` front matter; the change touches the fixed
  sensitive paths `.github/workflows/**` (`ci.yml`, `docs.yml`) and `**/*schema*` (the
  vendored A2UI schemas, the extension schemas under `docs/a2a/ext/`, the schema contract
  tests), which raises the inferred tier 3.
- **Human sign-off:** @MadaraUchiha-314, "security review approved", 2026-10-10
  ([issue comment](https://github.com/MadaraUchiha-314/tiny-harness/issues/3#issuecomment-6098305723)),
  distinct from the PR approval of the same day.

## Checklist

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | Every trust boundary of `design.md` § Security design is enforced where the design says | pass | registry-only tool calls with schema validation (`harness/tools/models.py`), plugin containment and `${VAR}` rules (`plugins/loader.py`), channel membership and the task access policy (`service/a2a/task_store.py`, `durable/activities.py` intake), remote card validation (`agents/remote.py`), A2UI surface registry (`interaction/a2ui/surfaces.py`), redaction at the four points (`security/redactor.py`, executor, activity wrapper, store, o11y) |
| 2 | Untrusted inputs validated at ingress; injection surfaces covered | pass | A2A messages: extension check, whole-message scrub, participant assertion, envelope validation (`service/inbox.py`); tool arguments against the tool's schema; A2UI actions against the vendored schemas and the task's surfaces; plugin manifests against the published schemas; SQL through parameterised `sqlite3` calls; no shell; MCP `command` never expanded |
| 3 | Untrusted content cannot steer privileged behaviour | pass | tool results, sub-task and remote-agent results and agent participants' messages rendered inside the delimited untrusted block (`core/context.py`); role changes need an admin actor; `set_participant_role`, envelopes and task operations check the asserted participant |
| 4 | No secrets in code, config, logs or fixtures | pass | secrets only from the environment (`config.py` `SECRET_VARIABLES`); `tests/security/test_redactor.py`; the committed evidence grepped for key shapes (`e2e.md`, `trace.json`, logs); fixtures carry fake values |
| 5 | AuthZ fails closed | pass | no participant assertion → not found / refused (critic finding 1, `tests/integration/a2a/test_access.py`); unknown entity → typed error; ambiguous role → deny |
| 6 | Least privilege | pass | the server holds no model key; MCP subprocesses get `PLUGIN_ROOT`, `PLUGIN_DATA`, the manifest's `env` and the SDK's minimal defaults; renderers hold no secret; the Pages-hosted renderer reaches a harness only where CORS allows its origin |
| 7 | Every abuse case has a passing negative test | pass | `tests/security/` (24 tests, cases 2–9); case 1 (unauthenticated client) is the perimeter's by decision-003 and is documented in the deployment guide |
| 8 | New dependencies justified and from trusted sources | pass | `design.md` § Dependencies (minimalism ladder) incl. `@a2a-js/sdk`; shadcn's generated components and `@shadcn/react`, `radix-ui`, `tailwindcss`, `lucide-react`, `cn`, `class-variance-authority`, `tw-animate-css` from the npm registry at pinned versions in `bun.lock` |

## Residual risk for the owner

The harness performs no authentication (decision-003): a deployment without an
authenticating perimeter is insecure by construction, and the participant assertion
(`X-Participant-Id`, message metadata) is self-asserted. The deployment guide says so;
accepting that for the first release is the owner's decision, already taken in
decision-003 and restated for the sign-off.
