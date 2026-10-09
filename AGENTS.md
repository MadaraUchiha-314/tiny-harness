# Working in tiny-harness

tiny-harness is a tiny agent harness. Work in this repository is delivered through
[the-loop](https://github.com/MadaraUchiha-314/the-loop), a product-development-lifecycle
harness.

## Before you change anything

1. Read [`.the-loop/harness-config.yaml`](.the-loop/harness-config.yaml) and the
   the-loop skill (`skills/the-loop/SKILL.md` in the installed plugin) with the
   references it points to. They define the process; don't re-derive it here.
2. Every change is a work item with a GitHub issue. Its specs and gate records live in
   `docs/specs/<id>/` and are checked in.
3. Follow the phases the work item selected. Record verification evidence under
   `docs/specs/<id>/evidence/`, and update affected capability docs in
   `docs/capabilities/` in the same pull request as the change.
4. Reach GitHub through the-loop's verbs (`the-loop ticket`, `comment`, `ask`, `pr`)
   when the CLI is available.

Explicit user instructions and the work item's frozen phase selection govern scope and
approvals.

## Where things live

| Path | What it holds |
|------|---------------|
| `.the-loop/` | the-loop's per-repo config: `harness-config.yaml`, `collaborators.yaml`, `manifest.yaml` |
| `.claude/settings.json` | Claude Code permissions and the the-loop plugin marketplace |
| `docs/specs/<id>/` | One folder per work item: spec chain, state, evidence |
| `docs/capabilities/` | Current behaviour, one doc per capability |
| `docs/architecture/` | Architecture index |
| `docs/decisions/` | Decision records |
| `docs/learnings/` | Learnings from user and system feedback |
