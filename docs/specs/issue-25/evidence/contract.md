# Contract tests

Issue #25, verification run on 2026-10-12 against `loop/issue-25` at `2393e75`.
Testing-plan rows: T3.

`uv run pytest tests/contract`

```text
36 passed in 2.99s
rc=0 secs=4
```

Snapshots changed in this PR, each regenerated on purpose:

- **Agent card:** it lists the status and commands extensions, and the commands list is
  in registration order.
- **API snapshots:** `hooks` (`command.invoked`, `AbandonObserver`,
  `HookManager.abandon`), `plugins` (`CommandDef`, `commands=`), `service`
  (`complete_message`, `plugins=`, `commands=`, `builtin_commands=`), `config`
  (`models`, `reasoning_effort`), and the new `home` and `models` catalog.
- **JSON Schemas:** `docs/a2a/ext/{task,status,commands}.json` and
  `docs/plugins/commands.json`. `status.json` keeps `sub_state` an open string.
