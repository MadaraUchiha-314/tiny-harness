---
type: evidence
workItem: issue-25
---

# Security review: Make the CLI/TUI experience seamless

## Security review (gate)

- **Mechanism:** the-loop's checklist, the fallback that `reference/security.md` names.
  This session has no built-in `/security-review` skill. Each item below was checked
  against `git diff origin/main...HEAD`.
- **Effective risk tier: 4.** The diff touches `**/*schema*` paths
  (`tests/contract/snapshots/settings.schema.json` and `tests/contract/test_ext_schemas.py`).
- **Human sign-off:** this tier needs a named human to sign off this round before the
  work item completes. **Pending:** it was requested from @MadaraUchiha-314 on PR #26.

| Round | Mechanism | Outcome | Link |
|-------|-----------|---------|------|
| 1 | the-loop checklist (fallback) | Three findings: one high, now fixed; two low, one won't-fix and one sent to the human. All 8 checklist items pass | this file |

### Checklist

| # | Item | Result | Evidence |
|---|------|--------|----------|
| 1 | Every trust boundary in `design.md` § Security design is enforced where the design says | pass, once S1 is fixed | **AuthN/AuthZ:** `AccessPolicy` on every task operation; `sender_of` (`tiny_harness/service/a2a/executor.py`) makes the request's `X-Participant-Id` decide; the inbox validator authorizes a control before it interrupts (`workflows.py` `_inbox_validator`); `refuse_watcher` on cancel. **Input:** see 2. **Secrets:** see 4. **Least privilege:** see 6. **Fail closed:** see 5. **Cost:** `/sub-task` passes through the limits middleware (`test_sub_task_flood.py`, 429) |
| 2 | Untrusted inputs are validated at ingress; injection surfaces are covered | pass | **Commands:** a command name must match `NAME_PATTERN` and the arguments are opaque text. `/model` checks the catalog's allowlist and `/effort` a closed set, and neither echoes a refused value. `/sub-task` stores its text only as a goal. **Server-controlled fields:** `lifecycle`, `model` and `reasoning_effort` in a client envelope are refused (`test_server_controlled_fields.py`). **Tool-call JSON:** arguments are depth-bounded before parsing (`harness/models/json_args.py`). **No shell, path or network use** in any built-in |
| 3 | Untrusted content cannot steer privileged behaviour | pass | **Replies:** a command's reply is the workflow's own concatenation, never a template (`_run_command`). **History note:** a participant's `/sub-task` reaches the parent's history as a quoted name (`json.dumps`). **Remote executors:** their replies are shown as text and change state only through the hook contract (`test_remote_command_executor.py`) |
| 4 | No secrets in code, config, logs or fixtures | pass | The generated `config.toml` says secrets come from the environment. The e2e run asserts no secret value appears in the trace or the server log (`evidence/e2e.md`). Evidence is redacted to `~` |
| 5 | AuthZ checks fail closed | pass | **Identity:** no asserted participant means `InvalidParams`, and a stranger gets not-found. A sender with no role is refused by the role policy. **Configuration:** an empty `models` list, or one missing the default, is a configuration error (exit 2). **Home:** an unsafe home or config file exits 2, with no fallback |
| 6 | Least privilege | pass | `~/.tiny-harness` is created `0700` and `config.toml` `0600` (`stat` in `evidence/manual.md`). The server binds `127.0.0.1` by default |
| 7 | Every abuse case has a passing negative test | pass | Cases 1–10, one line each, in `evidence/security.md` (68 security tests pass) |
| 8 | New dependencies are justified and trusted | pass | None added: `pyproject.toml`, `uv.lock` and `renderers/web/package.json` have no new packages |

### Findings

| # | Finding | Severity | Disposition |
|---|---------|----------|-------------|
| S1 | A message's metadata `participant_id` overrode the request's `X-Participant-Id`. A watcher could complete the task, or run `/model`, `/effort` or `/sub-task`, by naming the reporter (abuse case 4 bypass). Found in self-review round 1 | high | **fixed**: `10563b4`, with the regression test `test_a_watcher_cannot_complete_by_naming_the_reporter_in_the_message` |
| S2 | The built-in role policy limits watchers only for the built-in commands that change the task. A plugin command (for example `/deploy`) runs for a watcher unless its plugin adds a `command.invoked.pre` check | low | **escalated (decision for the human):** abuse case 4 lists only the built-ins, so the code meets the spec. The question is whether plugin commands should default to "no watchers". It is raised in the PR briefing |
| S3 | An `~/.tiny-harness` that already exists is not narrowed to `0700` if it is wider | low | **won't fix**: the directory is the user's own. It is refused when it is a symlink, a non-directory or owned by someone else (abuse case 7). Changing the mode of an existing directory the user may have set up deliberately would be surprising. Only newly created directories get `0700` (abuse case 8) |
