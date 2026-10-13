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
- **Risk tier:** 3. Inferred: the change touches the model's instructions but no
  sensitive path (no `*schema*`, `.the-loop/`, workflows, auth, secret or credential
  path). Tier 3 waits for a human approval of the PR.
- **Human sign-off:** n/a (risk tier below 4).
