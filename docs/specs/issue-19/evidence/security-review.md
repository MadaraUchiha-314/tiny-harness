---
type: evidence
workItem: issue-19
---

# Security review: Support connecting to any OpenAI-compatible API

The security review of `755ccb6..d9251a1` found no vulnerability at confidence 8/10 or
above. Every abuse case from the requirements has a passing negative test
([`security.md`](security.md)), including the four hardening fixes from critic round 1.
The work item is **risk tier 4**: it touches the sensitive path `**/*schema*`
(`tests/contract/snapshots/settings.schema.json`). It therefore waits for a named human
sign-off on this review.

## Security review (gate)

- **Mechanism:** Claude Code's built-in `security-review` skill. A sub-task traced the
  production diff (`tiny_harness/config.py`, `harness/models/openai_adapter.py`,
  `harness/models/openai_chat.py`, `harness/models/llm.py`, `harness/core/loop.py`,
  `harness/core/inprocess.py`, `service/o11y/hook.py`, `service/runtime.py`) against
  the requirements' Security considerations and the design's Security design. It
  reported only candidates at confidence 8/10 or above.
- **Outcome:** pass. No findings.
- **Findings:** none. The candidates it considered and rejected, and why:

  | Candidate | Why rejected |
  |-----------|--------------|
  | The key is sent to an arbitrary `base_url` | The operator configures the endpoint, and the configuration is trusted. Sending a key over `http` to a non-loopback host, and credentials inside the URL, are both refused at startup. |
  | The validator and httpx parse the URL differently, which could defeat the loopback check | httpx parses the same normalized `HttpUrl` string the validator checked. Names are never resolved. `localhost.` and IPv4-mapped addresses fail closed. |
  | A redirect carries the key to another host | Redirects are off for any custom endpoint (`follow_redirects=False`), and a test covers it. |
  | `OPENAI_BASE_URL`, `OPENAI_ORG_ID` or `OPENAI_PROJECT_ID` reach a custom endpoint | The base URL is always passed explicitly, and the organization and project headers are omitted. The startup warning names the variable, never its value. |
  | The keyless placeholder key is sent | `Authorization` is removed on every request; a test covers it. |
  | Log or span data exposes a path, a query or the key | Only `scheme://host[:port]` is emitted. Credentials inside the URL are refused. |
  | The redactor loses the key | `secret_values` still includes the key whenever one is set. |
  | Parse-error messages carry endpoint data | The data comes from the server, not from a secret; SDK error bodies were already passed through before this change. |
  | The endpoint names tools the harness never offered | This behavior predates the change and is the same on the Responses path; the tool registry decides what runs. |
  | Making `OPENAI_API_KEY` optional lets something run without authentication | The key is optional only when the trusted configuration sets `base_url`; every other required secret is still enforced. |

- **Earlier hardening, already fixed with tests:** deeply nested JSON (`538cd01`),
  empty or truncated streams (`072ba9f`), a non-absolute `base_url` (`1698416`) and a
  boolean `context_window_tokens` (`ac8a0a5`). See [`critic-review.md`](critic-review.md).
- **Human sign-off:** **approved** by @MadaraUchiha-314 on 2026-10-10
  ([PR #22 comment](https://github.com/MadaraUchiha-314/tiny-harness/pull/22#issuecomment-6102735114)).
  Risk tier 4 (sensitive path `**/*schema*`).
