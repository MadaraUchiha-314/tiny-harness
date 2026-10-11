---
type: evidence
workItem: issue-23
---

# Security review: Remove `TINY_HARNESS_PUSH_KEY` from the end-to-end architecture

The checklist passes with no open finding, but this change **removes a defence-in-depth
control**, so it carries an accepted residual risk that a human must own. The effective
risk tier is **4**: the diff touches `tests/contract/snapshots/settings.schema.json` (a
`**/*schema*` sensitive path) and changes how a credential is held at rest. A named
human security sign-off is therefore required before completion; it is requested on
PR #24 and recorded below when given.

## Security review (gate)

- **Mechanism:** the-loop checklist (the built-in `security-review` skill could not
  start on this machine; see Mechanism below).
- **Outcome:** pass, with no open finding. **Escalated** for a decision: the change
  accepts a residual risk (credentials stored in clear at rest).
- **Findings:** none. Verifying the checklist corrected one claim in `design.md` (no
  per-task ownership check guards push-config operations; the perimeter does, as
  before). That was a wording fix, not a vulnerability.
- **Human sign-off:** **pending.** Risk tier 4 (sensitive path `**/*schema*`, plus a
  security control removed). Requested from @MadaraUchiha-314 on PR #24.

## Mechanism

the-loop's checklist (`reference/security.md`), verified against
`git diff e5b3d64` at `7c3d8b2`. Claude Code's built-in `/security-review` skill was
tried first and could not start: every shell command on this machine exited non-zero
because `/tmp` was at its per-user quota (`pwd: write error: Disk quota exceeded`), and
the skill's preamble runs `git log` through that shell. The quota is unrelated to the
change.

## Checklist

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | Every trust boundary in design.md § Security design is enforced where the design says | pass | `Store` → disk: `SqliteStore.__init__` creates a new file with `O_CREAT \| O_EXCL`, mode `0600` (`store.py`); credential masking: `PushConfigRecord.token`/`authentication` are `SecretStr`, revealed only by the JSON serializer (`records.py`); legacy rows: `StorePushConfigStore._live` deletes and skips them (`push.py`) |
| 2 | Untrusted inputs validated at ingress; injection surfaces covered | pass | No new ingress. The A2A push-config request is validated by the a2a-sdk handler as before; the credential is stored as an opaque string and never interpolated into SQL (parameterised `INSERT`), a command or a path |
| 3 | Untrusted content cannot steer privileged behaviour | pass | The legacy check reads fields only an earlier tiny-harness wrote; a client cannot set `token_ciphertext` (not part of the A2A config, and `set_info` never writes it) |
| 4 | No secrets in code, config, logs or fixtures | pass | Fixtures use obvious dummies (`t0k3n-secret`, `cr3d`); T11 generated its key per run and recorded none; the ignored-variable warning is a constant that never reads the value (`key_in_log=0`) |
| 5 | AuthZ fails closed | pass | No authorization path changed: push-config operations are served by the a2a-sdk default handler for an existing task, as before. An uninterpretable (legacy) row is dropped, never delivered (integration scenario 7) |
| 6 | Least privilege | pass | Processes need one secret fewer; a new store file is owner-only, where before it inherited the umask (usually `644`) |
| 7 | Every abuse case has a passing negative test | pass | Abuse 1: `test_a_new_sqlite_store_is_readable_by_its_owner_only`; 2: `test_push_credentials_are_masked_when_printed`; 3: `test_an_exported_push_key_is_warned_about_without_its_value`; 4: `test_legacy_push_config_is_dropped` — see [security.md](security.md) |
| 8 | New dependencies justified and trusted | pass | None added; `cryptography` removed as a direct dependency |

## Findings

None open.

## Accepted residual risk (needs the human sign-off)

Push-notification credentials (`token`, `authentication`) are now stored in clear in
the default SQLite store. Anyone who obtains the store file — a copied backup, a volume
with loose permissions, or a file created before this version whose mode the change
deliberately leaves alone — reads every live push credential. The credential only
authenticates tiny-harness to that client's own webhook, and it lives at most
`[retention] push_configs` (30 days by default). Mitigations in this change: `0600` on a
new store file, `SecretStr` masking, and the deployment guide's instructions (`chmod
600` an existing file; an encrypting `Store` or encrypted volume for encryption at
rest). This is the ticket's stated direction, but accepting it is a security decision,
so it is put to a human rather than taken by the loop.

## Human sign-off

| Who | When | Decision | Link |
|-----|------|----------|------|
| _pending_ | | | |
