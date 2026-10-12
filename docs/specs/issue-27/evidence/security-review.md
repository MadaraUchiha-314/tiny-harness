---
type: evidence
workItem: issue-27
---

# Security review: Remote sub-tasks hear remote state changes between turns

> The `security-review` node's proof. See the-loop's `reference/security.md`.

## Security review (gate)

- **Mechanism:** the security-review skill (Claude Code's `/security-review`). A
  fresh-context sub-agent reviewed the code diff against the threat model in
  `requirements.md` § Security considerations and `design.md` § Security design. The
  review ran after both self-review rounds and alongside the critic round.
- **Outcome:** pass. The skill found no vulnerabilities at its reporting bar (confidence
  8 or more out of 10).
  - The critic round raised one security finding, critic #1: a push token could reach
    exported traces through the SDK's span recording of a registration error. It is
    fixed with `no_export` and `ExportGuard` and tested.
  - Self-review rounds 1 and 2 raised no security findings beyond critic #1's class.
    Round 1's #8 (refusal timing) is a won't-fix with its reason in requirements.md
    abuse case 2.
- **Findings:**

  | Source | Finding | Disposition |
  |--------|---------|-------------|
  | security-review skill | none | — |
  | critic round 1, #1 (high) | A push token in a remote's error text could be exported in an SDK client span (abuse case 7) | **fixed:** spans started during registration are never exported. Test: `test_a_failed_registration_exports_no_span_and_logs_no_token` |
  | self-review round 1, #8 (low) | Refusal latency differs between an unknown id and a wrong token | **won't-fix:** status and body are identical. Task ids are not secret, and the 256-bit token is what protects a stand-in. Recorded in abuse case 2. |
  | implementation (found by T8) | The SDK's DEBUG `Request body` log on a receiving server holds registered push tokens | **fixed:** `DropRequestBodies` filter. Tests: `test_unverifiable_pushes_…`, `test_the_sdk_request_body_debug_record_is_dropped` |

- **Checklist cross-check** (`reference/security.md`):

  | # | Item | Result |
  |---|------|--------|
  | 1 | Trust boundaries enforced as designed | pass: limits middleware, `MAX_PUSH_BYTES`, the token before Temporal, the validator (digest, id, mode, closed), and `GetTask` as the only state source |
  | 2 | Untrusted inputs validated at ingress | pass: size, header, and protobuf parse into `StreamResponse`; the path id only selects a workflow handle |
  | 3 | Untrusted content cannot steer privileged behaviour | pass: the push body is never applied; remote text reaches the parent's model only as a sub-task note |
  | 4 | No secrets in code, logs or fixtures | pass: the token is generated and used inside one activity; history holds only its SHA-256 digest; the log and trace paths are covered above |
  | 5 | AuthZ fails closed | pass: every verification failure is `401` and changes nothing; a failed registration falls back to follow |
  | 6 | Least privilege | pass: outbound calls go only to registered agents, with the harness's own participant id |
  | 7 | Every abuse case has a passing negative test | pass: `tests/security/test_remote_push.py` plus the unit tests named in `testing-plan.md` T8 |
  | 8 | New dependencies justified | n/a: none added |

- **Risk tier:** 4.
  - The change adds a new authenticated inbound network surface.
  - It touches a sensitive path: `tests/contract/snapshots/settings.schema.json` matches
    `**/*schema*`.
- **Human sign-off:** required at tier 4. It is requested on PR #28 together with the
  reviewer briefing, and is pending.
