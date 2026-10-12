# Manual first-run walkthrough

Issue #25, verification run on 2026-10-12 against `loop/issue-25` at `2393e75`.
Testing-plan row: T11.

The real TUI was driven through `tmux` (`send-keys` / `capture-pane`). Below, the
throwaway `HOME` is shown as `~`.

## 1. Build and install

```text
$ uv build --out-dir ~/.cache/i25/dist
Successfully built ~/.cache/i25/dist/tiny_harness-0.5.0-py3-none-any.whl
$ uv venv ~/.cache/i25/w && uv pip install -p ~/.cache/i25/w ~/.cache/i25/dist/*.whl
```

## 2. Bare `tiny-harness` with an empty `HOME`

```text
$ HOME=$(mktemp -d) tiny-harness
created default configuration ~/.tiny-harness/config.toml
configuration error: required secret is not set (OPENAI_API_KEY)
$ echo $?
2
$ stat -c '%a %n' ~/.tiny-harness ~/.tiny-harness/config.toml
700 ~/.tiny-harness
600 ~/.tiny-harness/config.toml
```

- **First run:** the default file is created, then the run stops with exit 2. The
  generated `[openai]` names a hosted model, and its secret comes only from the
  environment.
- **Pointing at Ollama:** following the plan, `[openai]` was then edited to the
  loopback Ollama (`base_url = "http://127.0.0.1:11434/v1"`, `api =
  "chat_completions"`, `model = "qwen3:1.7b"`, `models = ["qwen3:1.7b", "qwen3:8b"]`).

## 3. The TUI: one conversation over several messages

**First message.** It parks in `INPUT_REQUIRED · awaiting-next-message`. The Task tab
shows Settings and Sub-tasks.

```text
 tiny-harness · support-agent v0.1.0 · A2A 1.0 · http://127.…   task d846…0207 · INPUT_REQUIRED · awaiting-next-message
╭──────────────────────────────────────────────────────────────────────────────╮ Task  Plan  Trace
│ you › Reply with one short sentence: what is 2+2?                            │╸━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│                                                                              │ Goal
│ ── task → SUBMITTED                                                          │   Reply with one short sentence: what
│ ── task → WORKING                                                            │
│ agent › The task is to reply with "2+2 equals 4" as a short sentence. No     │   the-looper  reporter
│ tools are required for this simple calculation.                              │   tiny-harness  assignee
│ complete_step                                                                │ Settings
│ step: answer_task                                                            │   model  configured default
│ output: "2+2 equals 4"                                                       │   effort provider default
│                                                                              │ Sub-tasks
│ ── task → INPUT_REQUIRED · awaiting-next-message · your turn                 │   none
╰──────────────────────────────────────────────────────────────────────────────╯
▊  Enter to send as the-looper · / for commands                                                                        ▎
 ^d complete  ^c cancel  f2 task/plan/trace  f4 parent                                                      ▏^p palette
```

**Second message, `/status` and `/effort low`.** The second message is on the same task.
`/status` and `/effort low` reply with `⌘` lines, and the server log's model-call lines
were the same before and after them (2 → 2), so neither made a model call.

```text
 tiny-harness · support-agent v0.1.0 · A2A 1.0 · http://127.…   task d846…0207 · INPUT_REQUIRED · awaiting-next-message
╭──────────────────────────────────────────────────────────────────────────────╮ Task  Plan  Trace
│ output: "2+2 equals 4"                                                       │╸━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│                                                                              │ Goal
│ ── task → INPUT_REQUIRED · awaiting-next-message · your turn                 │   Reply with one short sentence: what
│ you › And 3+3? One sentence.                                                 │
│ ── task → WORKING                                                            │   the-looper  reporter
│                                                                           ▁▁ │   tiny-harness  assignee
│ agent › complete_step                                                        │
│ step: answer_task                                                            │ Settings
│ output: "3+3 equals 6"                                                       │   model  configured default
│ ── task → INPUT_REQUIRED · awaiting-next-message · your turn                 │ Sub-tasks
│ you › /status                                                                │
│ ▌ ⌘ Task d8464e7a-8cd3-4eea-9f52-37f4c6a80207 · Reply with one short         │
│ ▌ sentence: what is 2+2?                                                     │
│ ▌ State: INPUT_REQUIRED · awaiting-next-message                              │
│ ▌ Model: qwen3:1.7b (default)                                                │
│ ▌ Effort: provider default                                                   │
│ ▌ Plan: none                                                                 │
│ ▌ Sub-tasks: none                                                            │
│ you › /effort low                                                            │
│ ▌ ⌘ Effort set to low.                                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
▊  Enter to send as the-looper · / for commands                                                                        ▎
 ^d complete  ^c cancel  f2 task/plan/trace  f4 parent                                                      ▏^p palette
```

**`/sub-task`.** The reply names the new id, and the sub-task row appears.

```text
 tiny-harness · support-agent v0.1.0 · A2A 1.0 · http://127.…   task d846…0207 · INPUT_REQUIRED · awaiting-next-message
╭──────────────────────────────────────────────────────────────────────────────╮ Task  Plan  Trace
│ ── task → WORKING                                                            │ Goal
│ agent › complete_step                                                        │ is 2+2?
│ step: answer_task                                                            │
│ output: "3+3 equals 6"                                                       │ Participants
│ ── task → INPUT_REQUIRED · awaiting-next-message · your turn                 │   tiny-harness  assignee
│ you › /status                                                                │ Settings
│                                                                           ▇▇ │   model  configured default
│ ▌ ⌘ Task d8464e7a-8cd3-4eea-9f52-37f4c6a80207 · Reply with one short         │   effort low
│ ▌ sentence: what is 2+2?                                                     │ Sub-tasks · Enter opens
│ ▌ State: INPUT_REQUIRED · awaiting-next-message                              │ d846…07.1 · INPUT_REQUIRED · Draft a
│ ▌ Model: qwen3:1.7b (default)                                                │ one-line summary for the customer
│ ▌ Effort: provider default                                                   │
│ ▌ Plan: none                                                                 │
│ ▌ Sub-tasks: none                                                            │
│ you › /effort low                                                            │
│ ▌ ⌘ Effort set to low.                                                       │
│ you › /sub-task Draft a one-line summary for the customer                    │
│ ▌ ⌘ Starting a sub-task.                                                     │
│ ▌ Created sub-task d8464e7a-8cd3-4eea-9f52-37f4c6a80207.1.                   │
╰──────────────────────────────────────────────────────────────────────────────╯
▊  Enter to send as the-looper · / for commands                                                                        ▎
 ^d complete  ^c cancel  f2 task/plan/trace  f4 parent                                                      ▏^p palette
```

**Opening the sub-task.** Tab moves focus to the sub-task list, and Enter opens it. The
breadcrumb shows `parent › task …07.1`. The sub-task waits for its first message and
has inherited `effort low`.

```text
 tiny-harness · support-agent v0.1.0 · A2A 1.0 ·…   d846…0207 › task d846…07.1 · INPUT_REQUIRED · awaiting-next-message
╭──────────────────────────────────────────────────────────────────────────────╮ Task  Plan  Trace
│ ── task → SUBMITTED                                                          │╸━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│                                                                              │ Goal
│ ── task → INPUT_REQUIRED · awaiting-next-message · your turn                 │   Draft a one-line summary for the
│                                                                              │ Sub-tasks
╰──────────────────────────────────────────────────────────────────────────────╯
▊  Enter to send as the-looper · / for commands                                                                        ▎
 ^c cancel  f2 task/plan/trace  ^d complete  f4 parent  q quit                                              ▏^p palette
```

**Completing both tasks:**

- `ctrl+d` on the sub-task: `completed by the-looper`, `COMPLETED`.
- `f4` back to the parent. The parent was `WORKING`, because the sub-task's completion
  notes the parent and starts its turn, as the agent's own sub-tasks do.
- `ctrl+d` on the parent: the turn is interrupted, and the task ends `COMPLETED`.
- `ctrl+d` again: `── already COMPLETED`, so the key is inert.

```text
 tiny-harness · support-agent v0.1.0 · A2A 1.0 · http://127.0.0.1:8080/                      task d846…0207 · COMPLETED
╭──────────────────────────────────────────────────────────────────────────────╮ Task  Plan  Trace
│ ── task → INPUT_REQUIRED · awaiting-next-message · your turn                 │ Goal
│ you › /status                                                                │ is 2+2?
│ ▌ ⌘ Task d8464e7a-8cd3-4eea-9f52-37f4c6a80207 · Reply with one short         │ Participants
│ ▌ sentence: what is 2+2?                                                     │   the-looper  reporter
│ ▌ State: INPUT_REQUIRED · awaiting-next-message                              │   tiny-harness  assignee
│ ▌ Model: qwen3:1.7b (default)                                                │
│ ▌ Effort: provider default                                                   │ Settings
│ ▌ Plan: none                                                                 │   model  configured default
│ ▌ Sub-tasks: none                                                            │   effort low
│                                                                           ▆▆ │ Sub-tasks · Enter opens
│ you › /effort low                                                            │ d846…07.1 · COMPLETED · Draft a
│ ▌ ⌘ Effort set to low.                                                       │
│ you › /sub-task Draft a one-line summary for the customer                    │
│ ▌ ⌘ Starting a sub-task.                                                     │
│ ▌ Created sub-task d8464e7a-8cd3-4eea-9f52-37f4c6a80207.1.                   │
│ ── task → WORKING                                                            │
│ agent › completed by the-looper                                              │
│ ── task → COMPLETED                                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
▊  Enter to send as the-looper · / for commands                                                                        ▎
 ^c cancel  f2 task/plan/trace  ^d complete  f4 parent  q quit                                              ▏^p palette
```

```text
 tiny-harness · support-agent v0.1.0 · A2A 1.0 · http://127.0.0.1:8080/                      task d846…0207 · COMPLETED
╭──────────────────────────────────────────────────────────────────────────────╮ Task  Plan  Trace
│ you › /status                                                                │ Goal
│ ▌ ⌘ Task d8464e7a-8cd3-4eea-9f52-37f4c6a80207 · Reply with one short         │ is 2+2?
│ ▌ sentence: what is 2+2?                                                     │
│ ▌ State: INPUT_REQUIRED · awaiting-next-message                              │ Participants
│ ▌ Model: qwen3:1.7b (default)                                                │   the-looper  reporter
│ ▌ Effort: provider default                                                   │   tiny-harness  assignee
│ ▌ Plan: none                                                                 │
│ ▌ Sub-tasks: none                                                            │ Settings
│ you › /effort low                                                            │   effort low
│                                                                           ▁▁ │ Sub-tasks · Enter opens
│ ▌ ⌘ Effort set to low.                                                       │ d846…07.1 · COMPLETED · Draft a
│ you › /sub-task Draft a one-line summary for the customer                    │
│ ▌ ⌘ Starting a sub-task.                                                     │
│ ▌ Created sub-task d8464e7a-8cd3-4eea-9f52-37f4c6a80207.1.                   │
│ ── task → WORKING                                                            │
│ agent › completed by the-looper                                              │
│ ── task → COMPLETED                                                          │
│ ── already COMPLETED                                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
▊  Enter to send as the-looper · / for commands                                                                        ▎
 ^c cancel  f2 task/plan/trace  ^d complete  f4 parent  q quit                                              ▏^p palette
```

## 4 and 5. `--config` wins; a symlinked home is refused

```text
$ tiny-harness --config examples/demo/config.ollama.toml --help | tail -4
  --version             show program's version number and exit
  --config CONFIG       TOML configuration file (secrets from env)

configuration: examples/demo/config.ollama.toml (--config)
rc=0
$ ls -A $HOME
(empty)
$ ln -s elsewhere ~/.tiny-harness; tiny-harness
configuration error: refusing the default configuration: the directory is a symlink (~/.tiny-harness)
rc=2
```

## Findings

- **Every T11 step passed.**
- **Keyboard reach:** Tab cycles four stops, and the sub-task list is one of them. A
  keyboard-only user reaches it, but there is no direct key for it. That is enough for
  R9.4; a dedicated key could be a follow-up.
- **First run:** the first run ends with exit 2 until a model is set up (an
  `OPENAI_API_KEY`, or `base_url`). The message names the missing variable. This matches
  R2 and the fail-closed rule: there is no silent fallback.
