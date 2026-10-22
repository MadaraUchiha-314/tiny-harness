---
type: evidence
workItem: issue-38
---

# Security review: multi-modal input and output, with a voice mode

> The `security-review` node's proof. See `reference/security.md`.

## Security review (gate)

- **Mechanism:** Claude Code's built-in `/security-review` skill, run over the code diff
  `origin/main...HEAD` (`tiny_harness`, `renderers/web/src`, `examples/multimodal`,
  `pyproject.toml`) at `5f183ec`. A fresh-context reviewer traced untrusted input (A2A
  messages, file parts, URLs, file names, media ids, model and tool output, remote-agent
  results) to the sensitive operations (file system paths, HTTP responses, provider calls,
  workflow history, logs and spans). The skill's false-positive filter had nothing to filter.
- **Outcome:** **pass — no high- or medium-confidence finding.** Checked and found sound:
  - the media route uses the same participant resolution and `AccessPolicy` as the A2A
    routes, answers 404 when it fails, and validates ids;
  - store paths: an id pattern with no dot, atomic writes, `0700`/`0600` modes;
  - the guard on every ingress: no `url` parts from clients, the workflow accepts only its
    own task's media URLs, and controls refuse files;
  - a participant is required before any file is stored;
  - served content: raster images and audio only, signatures checked, `nosniff`,
    `default-src 'none'`, and a sanitised `Content-Disposition`;
  - both clients send the identity header only to their own origin, and only for the task
    on screen;
  - media ids come from `secrets.token_urlsafe(18)`;
  - spans carry ids and sizes only, transcripts are redacted before history, and
    `MediaAttachment` with bytes cannot be serialised;
  - the TUI cache uses validated ids, `O_NOFOLLOW | O_EXCL` and mode `0600`.
- **Findings:** none. One hardening note, below the reporting bar and **accepted for now**:
  `invoke_tool` does not check that a tool result's media ref belongs to the calling task.
  Today only `generate_image` (bound to the task) and operator-configured hooks can produce
  media parts, and MCP tools produce text only. Revisit if untrusted tool sources may ever
  return media parts.
- **Earlier rounds:** the security-relevant findings of the design critic (critic 5 ingress,
  6 audio duration), self-review (1.5 sniff trust, 2.2 the large-text body cap) and the
  code critic (GIF frames, transcript redaction, duration counting, media URLs pinned to
  the task) were fixed test-first before this round. See `self-review.md` and
  `critic-review.md`. The abuse-case tests are in `security.md` (T8).
- **Risk tier and human sign-off:** effective tier **4**. The change touches a fixed
  sensitive path (`**/*schema*`: `tests/contract/snapshots/settings.schema.json`, the
  extension schemas) and adds an authenticated HTTP route that serves user files. **A named
  human security sign-off is required** before the work item completes. It is requested
  from @MadaraUchiha-314 in the reviewer briefing on PR #39 — _pending_.
