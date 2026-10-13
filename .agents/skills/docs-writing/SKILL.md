---
name: docs-writing
description: How to write tiny-harness user and developer documentation — README.md and every page under docs/ except the-loop's spec chain. Use when you add, change or review a README, a guide, a configuration page, a developer page or a docstring that a user reads. Encodes the two personas, the quickstart-first layout, the configuration page format and Simplified Technical English (ASD-STE100) rules.
---

# Writing tiny-harness documentation

tiny-harness is a product. People install it and use it. Write for them, not for the
people who built it.

This skill covers `README.md` and the pages under `docs/` that a user reads:
`docs/cli/`, `docs/sdk/`, `docs/configuration/`, `docs/develop/` and `docs/index.md`.
It does not cover the-loop's records (`docs/specs/`, `docs/capabilities/`,
`docs/decisions/`, `docs/learnings/`). the-loop's own `writing` skill governs those.

## 1. Know the reader

Every user page is for one of three readers. Name the reader before you write.

| Reader | What they want | Where their pages live |
|--------|----------------|------------------------|
| **CLI user** | Install the `tiny-harness` command and chat with an agent in the terminal (the TUI). They do not write Python. | `docs/cli/` |
| **SDK user** | Run tiny-harness inside their own Python application, in production. They write code and operate servers. | `docs/sdk/` |
| **Contributor** | Change tiny-harness itself. | `docs/develop/`, `docs/architecture/` |

Rules:

- One page serves one reader. Do not mix CLI steps and SDK code on one page.
- Configuration is shared. Both CLI and SDK users read `docs/configuration/`.
- Internal detail (workflow names, activity names, hook points, requirement ids,
  issue numbers) belongs in contributor pages. Keep it out of CLI and SDK pages unless
  the user must type it or will see it.

## 2. Quickstart first, depth second

Each reader gets a quickstart. A quickstart is the shortest path to a working result.

- Five steps or fewer. Each step is one command or one short code block.
- Show the expected result after the last step ("You see …").
- Use defaults. Do not explain options in a quickstart. Link to the page that does.
- End with "Next steps": two to four links.

Deep pages come after the quickstart. A deep page explains one topic.

## 3. Configuration pages

`docs/configuration/` explains every key a user can set. Use plain words. Do not
assume the reader knows Temporal, A2A, MCP or OpenTelemetry. When a page must use one
of these terms, explain it in one sentence the first time.

Document each key with this pattern:

````markdown
### `key_name` {#key-name}

What it does, in one or two sentences.

- **Default:** `value` (or "none: you must set it")
- **Set it when:** the situation that makes a user change it.

```toml
[section]
key_name = "example"
```
````

- Give a key with `_` in its name an explicit anchor, `` ### `key_name` {#key-name} ``,
  so the docs site and markdownlint agree on the link target.
- Start each page with a short table of its keys and a complete minimal example.
- Give units for every number and the format for every duration (`"PT30S"` is
  30 seconds).
- Say what happens when the value is wrong ("tiny-harness does not start and names the
  key").

## 4. Write in Simplified Technical English

Use the rules of ASD-STE100 (Simplified Technical English). Apply the structural rules
in full. Apply the word rules as a direction.

### Structural rules: apply these

| Rule | Do | Do not |
|------|----|--------|
| Short sentences | 20 words or fewer in a procedure. 25 or fewer in a description. | Long sentences with many clauses. |
| One instruction per sentence | "Install uv. Run `uv sync`." | "Install uv and then run `uv sync`, which …" |
| Imperative for instructions | "Set `OPENAI_API_KEY`." | "You will want to set …", "You should set …" |
| Active voice | "tiny-harness creates the file." | "The file is created." |
| Simple tenses | "The task stopped." | "The task has stopped." (keep a compound tense only when it adds meaning) |
| No semicolons | Two sentences. | Clauses joined with `;`. |
| No phrasal verbs | "start", "stop", "remove", "read" | "spin up", "shut down", "take out", "dive into" |
| Short noun groups | Three nouns or fewer in a row. | "embedded Temporal dev server database path setting" |
| Lists for sequences | A numbered list for three or more steps. | Steps hidden in a paragraph. |
| One topic per paragraph | Six sentences or fewer. | A paragraph that covers two subjects. |
| Keep the hedge | "The call may fail." | Changing "may fail" into "fails". |

### Word rules: a direction

- **One word, one meaning.** Pick one term for one thing and use it every time. The
  project's terms are in the glossary below.
- **Verbs, not nouns.** "Configure the server", not "perform configuration of the
  server".
- **Plain words.** "use", not "leverage" or "utilize". "start", not "initiate". "help",
  not "facilitate".
- **No sales words.** Do not write seamless, robust, powerful, blazing, effortless,
  simply, just, easily. Show the fact instead.
- **Define a technical term once**, the first time a page uses it, or link to the
  glossary.

### Glossary: use these words

| Use | Meaning | Do not use |
|-----|---------|------------|
| harness | The tiny-harness program that runs the agent | engine, runtime (in user pages) |
| agent | The AI model plus its tools, skills and instructions | bot, assistant |
| task | One conversation with the agent, from the first message to Complete or Cancel | session, thread, job |
| configuration file | The TOML file tiny-harness reads at start | config, settings file |
| server | The tiny-harness A2A server (`tiny-harness serve`) | backend, API |
| worker | The process that runs tasks (`tiny-harness worker`) | executor |
| TUI | The terminal user interface (`tiny-harness tui`) | CLI app, console |
| web renderer | The browser user interface | web app, frontend, UI |
| plugin | A directory with a `plugin.json` that adds tools, skills, prompts or commands | extension, add-on |
| tool | A function the agent can call | action, function |
| skill | A `SKILL.md` playbook the agent can load | recipe |
| command | A `/name` message that the harness answers without the model | slash action |
| embedded Temporal | Temporal that tiny-harness starts on your computer | local Temporal, dev mode |
| remote Temporal | Temporal Cloud or your own Temporal cluster | cloud mode |

## 5. Page checklist

Before you finish a page, check each item:

1. The page names its reader in the first paragraph or by its section.
2. The first section gives the reader a result, not background.
3. Every command block can be copied and run as written.
4. Every claim matches the code. Read the code when you are not sure.
5. No sentence has a semicolon. No instruction sentence has more than 20 words.
6. Each technical term is in the glossary or is defined on the page.
7. Links use relative paths (`../configuration/models`) so the docs site checks them.
8. `bun run docs:build` in `docs/` passes (it fails on dead links), and
   `npx markdownlint-cli2` passes.

## 6. Diagrams

Use a Mermaid diagram when it is shorter than the prose it replaces. For an
architecture deep dive in `docs/develop/` or `docs/architecture/`, use the `archify`
plugin (enabled in `.claude/settings.json`). It reads the repository and draws an
interactive diagram. Check every node and edge against the code before you publish it.

## Source

The STE rules here follow ASD-STE100 Issue 9 as summarized by the
[asd-ste100 skill](https://github.com/danyuchn/asd-ste100-skill). This skill does not
reproduce the ASD dictionary. Get the standard from
[asd-ste100.org](https://www.asd-ste100.org/) when exact approved words matter.
