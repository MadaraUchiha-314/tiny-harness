---
type: evidence
workItem: "github:MadaraUchiha-314/tiny-harness#2"
---

# Security review: Repo tooling setup

## Security review (gate)

- **Mechanism:** the-loop checklist (`reference/security.md`), run by the session against
  `git diff origin/main...HEAD`. The built-in `/security-review` skill was started too;
  its result was not back when this record was written and will be added under
  "Built-in review" below.
- **Outcome:** pass. No finding blocks.
- **Findings:**

  | # | Finding | Severity | Disposition |
  |---|---------|----------|-------------|
  | 1 | `docs.yml` grants `pages: write` and `id-token: write` at workflow level, so the `build` job (which runs `bun install`) holds them too, not only `deploy`. Runs only on pushes to `main`, never on PR code | low (hardening) | Accepted for now; moving the two scopes onto `deploy` is a one-line follow-up, offered in the reviewer briefing |

- **Checklist:**

  | Check | Result |
  |-------|--------|
  | Untrusted PR code gets no write token or OIDC (abuse case 1) | `ci.yml` uses `pull_request`, never `pull_request_target`; workflow-level `contents: read`; no job widens it. Tested by `tests/unit/test_workflows.py` |
  | Only `release.yml` / env `pypi` can publish (abuse case 2) | `id-token: write` only on `publish`, which sets `environment: pypi`; PyPI's trusted publisher names this workflow and environment. Tested |
  | Failed checks block bump and publish (abuse case 3) | `publish` needs `bump` needs `checks` (`ci.yml`). Tested |
  | No credentials in the repository or evidence (abuse case 4) | No `secrets.*` beyond the implicit `GITHUB_TOKEN`; evidence redacted (scratch and home paths, placeholder git identity) |
  | Script injection | No attacker-controlled `github.event` field reaches a `run:` step. `head_commit.message` is used only in an `if:` expression (and only on pushes to `main`); the version reaches the shell through `env:` |
  | Unsafe deserialization | Tests use `yaml.safe_load` |
  | Supply chain | Python tools pinned by `uv.lock`, docs deps by `bun.lock` (`--frozen-lockfile`), markdownlint by exact version; actions on major tags (SHA pinning not adopted — hardening) |

- **Human sign-off:** required — risk tier 4 (`.github/workflows/**`, publish rights).
  Requested from @MadaraUchiha-314 in the reviewer briefing on PR #5; pending.

## Built-in review

Pending.
