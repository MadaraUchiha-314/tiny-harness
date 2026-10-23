# Add tools, commands and skills

A new harness has no tools. This page tells you how to give the agent what your product
needs. You can do it in two ways:

- **In code**, with arguments to `running_harness`.
- **In a plugin**: a directory that you list in the configuration file. A plugin can
  hold tools, skills, prompts, hooks and commands.

| You want the agent to … | Add a | Where |
|-------------------------|-------|-------|
| Call your API or read your data | **tool**, from an MCP server | a plugin's `mcp.json` |
| Follow a playbook for one kind of request | **skill** | a plugin's `skills/` |
| Know about your product and rules | **prompt** | a plugin's prompt files |
| Answer a `/name` message without the model | **command** | code, or a plugin's `commands.json` |
| Check or change what the agent does at a step | **hook** | a plugin's `hooks.json` |

## Add a command in code

A command is a message such as `/echo hi`. Your function answers it. The model does not
see it, so a command is fast and costs nothing.

```python
from tiny_harness.harness.commands import CommandInvokedIn, CommandResult, CommandSpec
from tiny_harness.service import running_harness

echo_spec = CommandSpec(name="echo", description="Repeat the text", argument_hint="<text>")


def echo(ctx: CommandInvokedIn) -> CommandResult:
    return CommandResult(reply=ctx.arguments)


async with running_harness(settings, commands=[(echo_spec, echo)]) as harness:
    await harness.wait()
```

- `ctx.arguments` is the text after the command name. `ctx.sender` is the sender's
  name. `ctx.task` describes the task.
- The function can be `async`.
- Clients see the command in the agent card, so the TUI and the web renderer show it
  when the user types `/`.
- To remove the built-in commands (`/model`, `/effort`, `/sub-task`, `/status`), add
  `builtin_commands=False`.

## Make a plugin

A plugin is a directory. Only `plugin.json` is necessary.

```text
my-plugin/
├── plugin.json                                 the name and version (necessary)
├── mcp.json                                    MCP servers: the tools
├── skills/
│   └── refunds/SKILL.md                        a skill
└── io.github.madarauchiha-314.tiny-harness/    parts only tiny-harness reads
    ├── prompts/rules.md                        add text to the system prompt
    ├── systemprompt.md                         replace the system prompt
    ├── hooks.json                              hooks
    └── commands.json                           commands
```

`plugin.json`:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "my-plugin",
  "version": "0.1.0",
  "description": "Tools and rules for the Acme support desk."
}
```

Load the plugin in one of two ways:

- In the configuration file: `plugins = ["path/to/my-plugin"]`.
- In code: `running_harness(settings, plugins=[Path("path/to/my-plugin")])`.

Plugins from code load after the plugins in the configuration file. The format follows
[Agent Plugins 1.0](https://agent-plugins.org/). If `plugin.json` is not valid, tiny-harness
does not load the plugin. If one part is not valid, tiny-harness skips that part and
loads the rest.

## Add tools with an MCP server

A tool is a function the agent can call. tiny-harness gets tools from
[MCP](https://modelcontextprotocol.io/) servers. MCP is an open protocol for tools.
Write a small MCP server, or use an existing one.

`mcp.json`:

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "orders": {
      "type": "stdio",
      "command": "python",
      "args": ["orders_server.py"],
      "cwd": "${PLUGIN_ROOT}"
    }
  }
}
```

- The agent sees each tool as `<plugin>/<server>.<tool>`, for example
  `my-plugin/orders.get_order`.
- `"type": "stdio"` starts the server as a child process. For a server that runs
  elsewhere, use `"type": "streamable-http"` and a `url`.
- `${PLUGIN_ROOT}` is the plugin directory. `${PLUGIN_DATA}` is a private data
  directory for the plugin.
- The server process gets only the `env` you list, plus `HOME`, `PATH`, `USER`,
  `SHELL`, `TERM` and `LOGNAME`. It never gets your API keys.
- tiny-harness retries a failed tool call only when the MCP server marks the tool as
  idempotent or read-only. Mark a tool that changes data (for example, "send a refund")
  as neither, so it never runs twice.

## Add a skill

A skill is a playbook in Markdown. The agent sees the name and description of every
skill. It reads the full text only when it needs it.

`skills/refunds/SKILL.md`:

```markdown
---
name: refunds
description: How to decide and issue a refund for an order, within policy.
---

# Refunds

1. Call `my-plugin/orders.get_order` with the order id.
2. ...
```

The directory name must be the same as `name`. A skill can also hold `scripts/`,
`references/` and `assets/` directories, and its own `mcp.json`. The format is
[Agent Skills](https://agentskills.io/).

## Change the system prompt

The system prompt has seven sections: `role`, `task`, `participants`, `tools`, `skills`,
`agents` and `rules`.

- To add text to one section, write a Markdown file in
  `io.github.madarauchiha-314.tiny-harness/prompts/`. Name the section in its front
  matter:

  ```markdown
  ---
  extends: rules
  ---

  You are the support agent of Acme. Ask before any refund.
  ```

- To replace the whole prompt, write
  `io.github.madarauchiha-314.tiny-harness/systemprompt.md`, with one `##` heading for
  each section.

## Add a command in a plugin

`commands.json` lists the commands. Each command names the hook that answers it.

```json
{
  "commands": [
    { "name": "deploy", "description": "Deploy to an environment", "argument_hint": "<env>", "hook": "deploy-body" }
  ]
}
```

`hooks.json` defines that hook. Its `points` must be exactly `["command.invoked.in"]`:

```json
{
  "hooks": [
    { "name": "deploy-body", "points": ["command.invoked.in"], "url": "https://hooks.example.com/rpc" }
  ]
}
```

The schema is in
[`docs/plugins/commands.json`](https://github.com/MadaraUchiha-314/tiny-harness/blob/main/docs/plugins/commands.json).

## Add a hook

A hook runs your code before, during or after a step of the agent. For example, a hook
on `tool.invoked.pre` can refuse a tool call or change its arguments.

Each entry in `hooks.json` has a `name`, an optional `priority` (lower runs first,
default 500), the `points` it handles, and one of these:

| Key | Your code runs |
|-----|----------------|
| `import_path` | In the harness process. `"my_package.hooks:audit"` names a Python object that has `name`, `priority`, `points` and `async handle(point, ctx)` |
| `url` | On your HTTP server, as JSON-RPC 2.0 |
| `mcp` | On an MCP server, as the tool `hooks.<operation>.<phase>` |

A hook that fails stops the step. tiny-harness then retries the step or fails the task.
It never ignores the failure.

The [hooks reference](../capabilities/hooks) lists every hook point.

## Use your own media services

The agent can hear audio, speak and make images. The
[`[speech_to_text]`, `[text_to_speech]` and `[image_generation]`](../configuration/media)
sections use OpenAI. To use another service, write a class and give an instance to
`Harness`. An instance replaces its section of the configuration file.

| Argument of `Harness` | Base class | Your class implements |
|-----------------------|------------|-----------------------|
| `speech_to_text` | `SpeechToText` | `async transcribe(audio, *, media_type, name, language)` returns a `Transcript` |
| `text_to_speech` | `TextToSpeech` | `stream(text, *, voice, instructions)` yields audio chunks in its `format` |
| `image_generator` | `ImageGenerator` | `async generate(prompt, *, size)` returns a `GeneratedImage` |
| `media_store` | `MediaStore` | Where the files of each task are kept. The default is `FileMediaStore`, a folder |

The base classes are in `tiny_harness.harness.models`. `MediaStore`, `FileMediaStore` and
`AudioFormat` are in `tiny_harness.harness.media`.

This example sends audio to your own speech-to-text service:

```python
from pathlib import Path

from tiny_harness.config import Settings
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.models import SpeechModelInfo, SpeechToText, Transcript
from tiny_harness.service import Harness


class MyTranscriber(SpeechToText):
    async def transcribe(
        self, audio: bytes, *, media_type: str, name: str = "audio", language: str | None = None
    ) -> Transcript:
        text = await my_service.transcribe(audio, media_type)  # your code
        return Transcript(text=text)


transcriber = MyTranscriber(
    EntityRef(kind=EntityKind.SPEECH_TO_TEXT, id="my-transcriber"),
    SpeechModelInfo(provider="my-service", model="v1"),
)
harness = Harness(Settings.load(Path("agent.toml")), speech_to_text=transcriber)
```

- The configuration file must have a [`[media]`](../configuration/media#media-settings)
  section. Without it, the agent takes no files, and tiny-harness does not use the
  instance.
- `build_runtime` takes the same four arguments.
- Do not retry in your class. Raise `RetryableProviderError` (from `tiny_harness.errors`)
  for a rate limit, a timeout or a server error, and tiny-harness tries again. Raise
  `ProviderError` for any other failure.
- A `TextToSpeech` gives its `format` as an `AudioFormat`. The TUI and the web renderer
  play 16-bit mono PCM at 24 kHz, so use that format.
- The [multi-modal example](example-multimodal) shows the OpenAI services at work.

## Connect other agents

The agent can give work to other A2A agents. List them in the configuration file. See
[Plugins and other agents](../configuration/plugins-and-agents).

## Next steps

- [Example: support agent](example): a plugin with two MCP servers, a skill and a
  prompt.
- [Example: images and voice](example-multimodal): photos, voice messages, spoken
  replies and generated images.
- [Deploy](deploy): run it for real users.
