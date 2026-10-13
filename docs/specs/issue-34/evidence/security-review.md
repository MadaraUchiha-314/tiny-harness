---
type: evidence
workItem: issue-34
---

# Security review: show the configured remote agents to the model

> The `security-review` node's proof. See `reference/security.md`.

## Security review (gate)

- **Mechanism:** the built-in security-review skill. A reviewer sub-agent read the
  production diff (`git diff origin/main...HEAD -- tiny_harness`) and traced the code it
  reaches (`render_untrusted_text`, `ContextWindow.instructions`, the remote-agent lookup
  in `service/durable/activities.py`, every builder of `core_intrinsics`). It then
  self-filtered false positives and reported only findings at confidence 8/10 or above.
- **Outcome:** pass. No vulnerability at or above the reporting threshold.
- **Findings:** none. What was checked, and why each concern is not exploitable:

  | Concern | Result |
  |---|---|
  | Card text escapes the untrusted block or forges a section tag or roster entry | Not possible. Every Unicode category C character (`\n`, `\r`, NEL, bidi overrides, zero-width, tag characters) becomes a space, and `\s+` collapses U+2028/2029 and other separators. So no field can start a new line, and ASCII `<`/`>` become `‹`/`›` before the cap. Full-width look-alikes (`＜`) are other code points. They stay on one line inside the untrusted block, which is ordinary in-data injection, not a structural escape. |
  | The wrapper itself | The `source` attribute and the preamble are fixed strings, and the outer `<agents>` tag comes from the section name. The remote side controls none of them. |
  | `spawn_subtask` check bypass (case, whitespace, empty, version) | Exact string membership against the registry ids, the same ids the remote activity looks up. `""` is refused, only `None` runs locally, and the model cannot choose a version. `InProcessOperations.bind` is the only builder, and the default `known_agents` fails closed. |
  | URL or secret leak into context or logs | The roster reads only the id, the card's name and description, and its skills. The logs carry ids and field names. The error lists ids the model already sees. |
  | A different card than the agent called | `registered_agents` lists the version a delegation resolves (`*`). |
  | Card changing after startup | Not possible. The roster is built once from the cards fetched at start. |

- **Negative tests:** abuse cases 1–4 in `tests/security/test_agent_roster.py`, and the
  end-to-end hostile-card scenario in `tests/integration/agents/test_agents_roster.py`
  ([security.md](security.md)).
- **Code after the review:** two critic fixes landed after this review. `71c1545`
  refuses an empty `agent` even when registered, and `433f694` keeps one truncation
  record per skill field. Both only tighten behaviour, and neither adds an input, a
  sink or a boundary, so the verdict stands.
- **Risk tier:** 3. Inferred: the change touches the model's instructions but no
  sensitive path (no `*schema*`, `.the-loop/`, workflows, auth, secret or credential
  path). Tier 3 waits for a human approval of the PR.
- **Human sign-off:** n/a (risk tier below 4).

## Security review of R5–R7 (round 2)

- **Mechanism:** the built-in security-review skill, on the branch at `3104ea1`. A
  reviewer sub-agent read `git diff main...HEAD -- tiny_harness examples`, focused on the
  new trust boundary. Findings below confidence 8/10 are dropped.
- **Outcome:** pass. No vulnerability at or above the reporting threshold.
- **What was checked, and why each concern is not exploitable:**

  | Concern | Result |
  |---|---|
  | Impersonating the harness's own id (`tiny-harness`) to become a trusted delegator | Not a new escalation. Identity is the perimeter's assertion (decision-003). Whoever can assert that id was already a participant of every agent-mode task. The only new power is `lifecycle`, `model` and `reasoning_effort` on a task the sender creates. Since `fe0587d`, `model` must also be selectable. |
  | The brief-only start reaching an existing task | Not reachable. The SDK refuses an unknown `task_id` before the executor runs, a non-participant's lookup returns nothing, and a new task's id is the server's. |
  | Sender as reporter; participant mode | The sender becomes reporter only of a task it creates. Naming participants on a new task was already open. Participant mode makes no model call and grants no access. |
  | SSRF through delegation | Targets are registered agent ids only. `self` comes from operator config, and the id `self` is reserved. |
  | Data sent to another agent | The open fields only (name, goal, description, criteria). No participants, history or tokens. |

- **Deployment note → documented:** the harness's call to itself carries
  `X-Participant-Id: tiny-harness` with no credential. A gateway that passed client-supplied
  values of that header would let any client act as the harness. `docs/sdk/deploy.md`
  now says to route the self-call internally and that the gateway must always replace
  the header (`fe0587d`).
- **Risk tier: 4 (raised from 3).** R5 and R7 touch `tests/contract/snapshots/settings.schema.json`,
  a fixed sensitive path (`**/*schema*`). R7 also loosens a guard behind an allowlist
  (`[server] delegators`): a creator may now set server-controlled fields. That is a
  security decision for a human.
- **Human sign-off:** **required, pending.** A named human must approve this security
  review on PR #35, separately from the PR approval, and decide the trust rule
  (proposal, (b) or (c)).
