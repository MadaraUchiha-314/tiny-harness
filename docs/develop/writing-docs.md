# Write documentation

tiny-harness is a product, and its documentation is part of it. The full rules are in
the project skill
[`.agents/skills/docs-writing/SKILL.md`](https://github.com/MadaraUchiha-314/tiny-harness/blob/main/.agents/skills/docs-writing/SKILL.md).
Claude Code and Codex load it when they write docs. This page is the summary for people.

## Who reads what

| Reader | Section |
|--------|---------|
| CLI user: chats in the terminal, writes no code | `docs/cli/` |
| SDK user: runs tiny-harness in a Python application in production | `docs/sdk/` |
| Both | `docs/configuration/` |
| Contributor | `docs/develop/`, `docs/architecture/` |

One page serves one reader. Keep internal names (activities, hook points, requirement
ids) out of CLI and SDK pages.

## Quickstart first

Each reader has a quickstart: five steps or fewer, defaults only, the expected result
at the end. Deep pages come after it, one topic each.

## One pattern for each setting

Each setting on a configuration page has: what it does, its default, when to change
it, and a TOML example. Explain technical words the first time.

## Simplified Technical English

Write in the style of [ASD-STE100](https://www.asd-ste100.org/):

- 20 words or fewer in an instruction sentence. 25 or fewer in a description.
- One instruction in each sentence. Use the imperative: "Set the key."
- Active voice and simple tenses.
- No semicolons, no phrasal verbs ("spin up"), no sales words ("seamless").
- One word for one thing. The skill has the glossary.

## Diagrams

Use Mermaid for small diagrams. For an architecture deep dive, use the archify plugin.
It reads the code and draws an interactive diagram. Check each part of the diagram
against the code.

## Before you open a pull request

```sh
cd docs && bun run docs:build     # fails on a dead link
npx markdownlint-cli2 "**/*.md"
```
