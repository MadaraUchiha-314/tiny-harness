# Evidence: documentation (task 21)

Task 21 brings the user and reference documentation in line with what issue-25 built,
per the NFR "Documentation". Where the build differs from `design.md` (see the
deviations noted on the task commits), the docs describe the built behaviour.

## Documents changed

| Document | Why |
|----------|-----|
| `README.md` | Install → bare `tiny-harness` opens the TUI → `~/.tiny-harness/config.toml` created (`0700`/`0600`, `--config` wins); the conversation lifecycle (parks `INPUT_REQUIRED · awaiting-next-message`; Complete `ctrl+d` / Cancel `ctrl+c` or the buttons); the four slash commands; an unregistered `/word` reaches the model; five extensions |
| `docs/guide/getting-started.md` | New "From `pip install` to a conversation" section (default file, the lifecycle diagram, Complete/Cancel, the commands table); the demo flow now parks and is completed; the e2e tests' new steps |
| `docs/a2a/extensions.md` | Rows for the status and commands extensions linking their v1 pages; a "Completing a task" section for the `{"kind": "control", "action": "complete"}` envelope, its refusals and `complete_message` |
| `docs/capabilities/configuration.md` | CLI with no subcommand, `--help` naming the file, the default file and its safe creation, `models` / `reasoning_effort`, the SDK entry points (`plugins=`, `commands=`, `builtin_commands=`, `complete_message`, `tiny_harness.home`); history row |
| `docs/capabilities/tasks-and-plans.md` | `lifecycle`, `model`, `reasoning_effort` as server-controlled fields; conversation tasks park with a sub-state; participant completion; `/sub-task` children and settings inheritance; history row |
| `docs/capabilities/a2a-server.md` | Status and commands extensions on the card; terminal and watcher refusals; the control envelope path; command dispatch and its reply; history row |
| `docs/capabilities/surfaces-and-renderers.md` | TUI top bar sub-state, `ctrl+d` / `ctrl+c` / `f4` / `enter`, `/` completion, `GetTask` polling; web state and sub-state badges, Complete / Cancel task buttons, ← Parent, the command listbox, `?fixture=controls`; history row |
| `docs/capabilities/models.md` | Per-request `model` and `reasoning_effort`, the three provider effort mappings, `ModelCatalog`, the per-model context window, span attributes; history row |
| `docs/capabilities/hooks.md` | `command.invoked` context, per-command body filter, the built-in role `pre` executor, refusal and failure replies; `AbandonObserver` / `HookManager.abandon`; history row |
| `docs/capabilities/plugins.md` | `commands.json`, command-owned hooks, override, built-in commands, `builtin_commands=False`; history row |
| `docs/capabilities/entities-and-registry.md` | The `command` kind, the `Command` entity and `CommandRegistry`; history row |
| `docs/decisions/decision-007.md` | New decision record: `INPUT_REQUIRED` + metadata sub-state (A2A forbids new `TaskState` values), the control envelope for completion, the programmatic hook-extensible command registry; context, decision, consequences, alternatives |
| `docs/decisions/decisions.md` | Index row for decision-007 |
| `docs/specs/issue-25/tasks.md` | Task 21 ticked |

## Checks

| Check | Command | Result |
|-------|---------|--------|
| markdownlint (pre-commit) | `uv run pre-commit run markdownlint --files <the changed Markdown>` | Passed |
| Docs site build, dead links | `(cd docs && bun run docs:build)` | `build complete`, exit 0, no dead links reported (only the existing chunk-size warning) |
