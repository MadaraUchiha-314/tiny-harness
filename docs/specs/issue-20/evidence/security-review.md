---
type: evidence
workItem: issue-20
---

# Security review: `tiny-harness tui` never asserts a participant

## Security review (gate)

- **Mechanism:** Claude Code's built-in security-review skill (`/security-review`), run
  over the branch diff against `origin/main` at `9748d03`, with `bugfix.md` § Security
  considerations and `design.md` § Security design as the threat model.
- **Outcome:** pass. The review reported no high-confidence vulnerability, so the
  false-positive filter had nothing to check.
- **Findings:** none. Areas checked, with the mechanism that holds in each:

  | Area | Mechanism verified in the diff |
  |---|---|
  | Header / CRLF injection | `tui_participant` (`cli.py`) accepts only non-empty printable ASCII, which rejects CR, LF, NUL and every other control character before anything connects. httpx refuses CR/LF in a header too. |
  | AuthN / AuthZ | No server code changed. The executor still refuses a message that asserts nobody, and `AccessPolicy` still checks membership against the asserted id. The id is self-asserted (decision-003), and any A2A client could already send any id, so a client-side default adds no capability. |
  | Fail closed | Blank flag, undeterminable OS user, or an id outside printable ASCII → exit 2, no connection. The `participant or "you"` fallback is gone, so the client never invents an identity. |
  | Untrusted display | The composer placeholder shows the user's own local value. Server-supplied fields the TUI renders are unchanged. |
  | PII | The OS user name now goes to the server the user configured, by default. That is the intended identity assertion, it is documented (README, guide, capability doc), and `--participant` overrides it. It is not logged by the CLI. In committed evidence it is redacted to `[os-user]`. |
  | Other | The diff adds no subprocess, shell, file path, deserialization, template or new dependency. |

  Earlier security-relevant findings, fixed with tests: a non-ASCII or control-character
  id would not survive the header's latin-1 decoding or would break HTTP (self-review
  round 1, `2adbe39`, R1.8), and an OS user name with surrounding whitespace that h11
  would reject (critic round 2, `7bb154d`). Abuse case 1 (no participant → refused) and abuse case 2
  (an asserted id gets no extra trust) pass unchanged: `tests/security` and
  `tests/integration/a2a` ([regression.md](regression.md) § T8).
- **Risk tier:** 3, the default. The change touches no fixed sensitive path
  (`**/*schema*`, `.the-loop/**`, `.github/workflows/**`, `**/auth/**`, `**/*secret*`,
  `**/*credential*`), and it adds no privilege or server-side surface.
- **Human sign-off:** not required at tier 3; the PR's `human-approval` gate still
  applies.
