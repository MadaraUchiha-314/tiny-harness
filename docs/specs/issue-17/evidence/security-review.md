---
type: evidence
workItem: issue-17
---

# Security review: Support embedded Temporal mode

## Security review (gate)

- **Mechanism:** Claude Code's built-in security-review skill (`/security-review`), run
  over the whole branch diff against `origin/main` at `1561d2f`, with the requirements'
  Security considerations and design.md § Security design as the threat model.
- **Outcome:** pass. The review reported no high-confidence vulnerability, so the
  false-positive filter had nothing to check.
- **Findings:** none. Areas checked, with the mechanism that holds in each:

  | Area | Mechanism verified in the diff |
  |---|---|
  | Planted or swapped binary | download dir `0700`; refused if another user owns it or others can write to it, and the same for each cached binary; a pinned `binary_path` must be an executable file and skips the cache; never the system temp dir |
  | Command injection | namespace, port and paths reach the SDK as separate arguments, with no shell; all come from trusted config |
  | Network exposure | `ip="127.0.0.1"` is a literal and the Web UI is off; every listening port of the dev server is verified loopback (T2); embedded mode refuses `address`, `tls` and `api_key` |
  | Data at rest | database, `-wal`/`-shm`, lock and TUI log are `0600`. The database is briefly at the umask, between the dev server creating it and the chmod right after start; no workflow data exists yet in that window |
  | Secrets | `TEMPORAL_API_KEY` is refused in embedded mode; the redactor still masks every configured secret, including in the TUI log; errors carry no secrets |
  | AuthN/AuthZ | `running_harness` builds the same A2A app as the old `commands.serve`; no access check removed |
  | Lifecycle | SIGTERM unwinds in order for the CLI and the programmatic `serve` (critic finding, fixed `f037412`) |

  Earlier security-relevant findings, all fixed with tests: the private download dir
  (design); ownership of the cache and binary (`0471c9b`); a dev server orphaned on a
  post-start failure (`44d8154`); `api_key` in programmatic embedded settings
  (`777bf60`); the owner-only TUI log (`83799a0`); SIGTERM orphaning via the programmatic
  `serve` (`f037412`). Abuse cases 1–8 each have a passing negative test
  ([security-tests.md](security-tests.md)).
- **Accepted residual risks** (requirements R7.3, documented in the deployment guide):
  the embedded frontend has no authentication on loopback, so other users of the same
  host can reach it; a SIGKILL of the harness can orphan the dev server.
- **Risk tier:** 4. The work adds attack surface (an unauthenticated local server, a
  binary download), which is the default tier 3, and touches the fixed sensitive path
  `**/*schema*` (`tests/contract/snapshots/settings.schema.json`), which raises it to 4.
- **Human sign-off:** @MadaraUchiha-314 (approver), 2026-10-10. The request on PR #18
  said one approving reply covers both the PR and this security review
  ([request](https://github.com/MadaraUchiha-314/tiny-harness/pull/18#issuecomment-6100603808)),
  and the reply was "approved"
  ([sign-off](https://github.com/MadaraUchiha-314/tiny-harness/pull/18#issuecomment-6100675826)).
