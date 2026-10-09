# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- [`.claude/settings.json`](.claude/settings.json) registers the `the-loop` marketplace
  (`MadaraUchiha-314/the-loop`) and enables the `the-loop@the-loop` plugin. Trust the
  repository's settings when prompted so the plugin installs; its SessionStart hook then
  points each session at `.the-loop/harness-config.yaml`.
- Run the-loop's commands as slash commands, e.g. `/the-loop:work-on <issue>`.
