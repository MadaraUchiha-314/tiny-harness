---
type: evidence
workItem: "issue-1"
---

# Verification: Init dev env

> issue-1 declared `test-planning` away, so the proof lives here. The checks are
> structural: this change adds config and docs, no code.

## Verification results

| What was verified | Command | Outcome | Evidence |
|-------------------|---------|---------|----------|
| `.the-loop/` holds exactly the three files the issue asks for | `ls -A .the-loop` | pass | [checks.md](checks.md#the-loop-folder) |
| `.claude/settings.json` is identical to the-loop's reference settings | `curl -sL <reference raw url> \| diff - .claude/settings.json` | pass | [checks.md](checks.md#claude-settings) |
| The settings register the the-loop marketplace and enable the plugin | `jq -e '.enabledPlugins["the-loop@the-loop"] and .extraKnownMarketplaces["the-loop"].source.repo=="MadaraUchiha-314/the-loop"'` | pass | [checks.md](checks.md#claude-settings) |
| `harness-config.yaml` and `collaborators.yaml` validate against the plugin's schemas (19.28.0) | `uv run --with pyyaml --with jsonschema python validate.py` | pass | [checks.md](checks.md#schema-validation) |
| `manifest.yaml` is the plugin's manifest, unchanged | `diff $PLUGIN/.the-loop/manifest.yaml .the-loop/manifest.yaml` | pass | [checks.md](checks.md#manifest) |
| The docs trees `/the-loop:init` creates exist | `ls -d docs/*/` | pass | [checks.md](checks.md#docs-trees) |
| No CLI config was scaffolded (out of scope per the issue) | `ls -A .the-loop` (no `cli-config.yaml`) | pass | [checks.md](checks.md#the-loop-folder) |
