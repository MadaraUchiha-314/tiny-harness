# Capability: dev-environment

> How an agent session is set up in this repository: the instruction files it reads,
> the Claude Code settings it runs under, and the-loop's per-repo config.

## What it is

The repository's developer environment for coding agents. Claude Code and other agent
harnesses (via `AGENTS.md`) get the same instructions; Claude Code also installs the
the-loop plugin from the repository's settings.

## Current behaviour

- The repository SHALL carry `AGENTS.md` as the harness-neutral instructions, and
  `CLAUDE.md` SHALL import it (`@AGENTS.md`) and add only Claude Code specifics.
- `.claude/settings.json` SHALL match the-loop's own
  [`.claude/settings.json`](https://github.com/MadaraUchiha-314/the-loop/blob/main/.claude/settings.json):
  the same permission allow-list, the `the-loop` marketplace
  (`github: MadaraUchiha-314/the-loop`) and `the-loop@the-loop` enabled.
- `.the-loop/` SHALL hold exactly three files: `harness-config.yaml`,
  `collaborators.yaml` and `manifest.yaml`. The the-loop CLI is not configured here: no
  `cli-config.yaml`, no Slack manifest.
- `.the-loop/collaborators.yaml` SHALL name `@MadaraUchiha-314` as the approver.
- The docs trees the-loop expects SHALL exist: `docs/specs/`, `docs/capabilities/`,
  `docs/architecture/`, `docs/decisions/` and `docs/learnings/`.

## Design

No design.md: issue-1 declared design away. The file layout follows the-loop's
`/the-loop:init` command and its manifest.

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-1 | Initial dev environment: agent instructions, Claude settings, the-loop init | [spec](../specs/issue-1/), [issue #1](https://github.com/MadaraUchiha-314/tiny-harness/issues/1) |
