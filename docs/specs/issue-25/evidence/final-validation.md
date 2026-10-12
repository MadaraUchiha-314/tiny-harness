---
type: evidence
workItem: issue-25
---

# Final validation: Make the CLI/TUI experience seamless

This file summarises the executed verification (`testing-plan.md` § Verification
results, run on 2026-10-12) and maps it onto the acceptance criteria. Raw output,
screens and the flow GIF are beside this file.

## Final validation evidence

| Acceptance criterion | How it was proved | Where |
|----------------------|-------------------|-------|
| **R1:** `tiny-harness` works straight after `pip install`; bare `tiny-harness` opens the TUI | T11 installed the built wheel into a fresh venv; bare `tiny-harness` opened the TUI. T1 parser tests: bare command is `tui`, the epilog names the file, `--help` creates nothing | [manual.md](manual.md) §2–3, [unit.md](unit.md) |
| **R2:** default `~/.tiny-harness/config.toml`, created safely, `--config` wins | T11 `stat` shows `700` and `600`. `--config … --help` names the flag file and leaves `$HOME` empty. A symlinked home exits 2. T8 abuse cases 7–8, plus the race tests (C2, C3) | [manual.md](manual.md) §2, §4–5, [security.md](security.md) |
| **R3:** a reply does not complete the task | T4: the turn ends `INPUT_REQUIRED · awaiting-next-message`, and a second message continues the same task. T2 lifecycle scenarios (conversation versus delegated) | [e2e.md](e2e.md), [integration.md](integration.md) |
| **R4:** `INPUT_REQUIRED` sub-states as an A2A extension | T3: the card lists the status extension, and `status.json` keeps `sub_state` an open string. T2/T4: the sub-state is in `Task.metadata` and in status updates | [contract.md](contract.md), [e2e.md](e2e.md) |
| **R5:** Complete and Cancel from the TUI and the Web UI | T11: `ctrl+d` completes the sub-task and the parent, and the keys go inert afterwards. T5/T6: the web Complete/Cancel states and the flow GIF. T2: completion interrupts a turn, and is refused while a sub-task is open. T8: watchers and strangers are refused | [manual.md](manual.md) §3, [ui.md](ui.md), [integration.md](integration.md), [security.md](security.md) |
| **R6:** slash commands from a programmatic registry; an unregistered `/x` goes to the model | T1: parser and registry. T2: dispatch scenarios. T8 abuse case 9 | [unit.md](unit.md), [integration.md](integration.md), [security.md](security.md) |
| **R6a:** commands through the hook system (`command.invoked`, plugin `commands.json`) | T1: plugin `commands.json` loading, including fail-closed on an invalid file (C1). T2: a plugin overrides a built-in, a `pre` hook refuses, and a remote body failure changes nothing | [unit.md](unit.md), [integration.md](integration.md) |
| **R7:** `/model` | T2: `/model` changes the next model request. T8 abuse case 1 (unlisted model refused) | [integration.md](integration.md), [security.md](security.md) |
| **R8:** `/effort` | T11: `/effort low` is set and inherited by the sub-task. T1: each adapter's effort mapping. T8 abuse case 2 | [manual.md](manual.md) §3, [unit.md](unit.md), [security.md](security.md) |
| **R9:** `/sub-task` | T11: the reply names the new id, the sub-task opens and goes back with `f4`. T2: the linked conversation child, and the parent's history note without a model turn. T8 abuse case 6 (rate limit) | [manual.md](manual.md) §3, [integration.md](integration.md) |
| **R10:** `/status` | T4: `/status` answers with no new `chat` span. T11: the server log's model-call lines were 2 before and 2 after | [e2e.md](e2e.md), [manual.md](manual.md) §3 |
| **R11:** the SDK keeps parity with the CLI | T1/T2: `running_harness` and `build_runtime` take `plugins=`, `commands=` and `builtin_commands=`; the public `complete_message`; API snapshots (T3) | [unit.md](unit.md), [contract.md](contract.md) |
| **NFR:** backwards compatibility | T10: a task stored before this change loads and its lifecycle is derived; an existing config loads | [migration.md](migration.md) |
| **NFR:** accessibility | T9: axe and keyboard reach on the web; every TUI action has a key | [accessibility.md](accessibility.md) |
| **Security considerations:** abuse cases 1–10 and fail-closed | T8: one negative test per case (68 pass). Security checklist: 8/8 pass, with the risk-tier-4 human sign-off pending | [security.md](security.md), [security-review.md](security-review.md) |

**Not executed:** the OpenAI-backed e2e tests, which need `OPENAI_API_KEY`. The offline
T4 covers the same flow.
