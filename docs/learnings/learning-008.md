# Learning 008: VitePress parses angle brackets in a code span that wraps lines

- **Date:** 2026-10-10
- **Source:** system-feedback
- **Work item:** issue-19

## What happened

`design.md` and `tasks.md` contained an inline code span holding a placeholder like
`<scheme>://<host[:port]>`, and line wrapping split that span across two source lines.
markdownlint passed. The docs site build in CI then failed with
`Element is missing end tag`: VitePress compiles each page as a Vue template, and a code
span split across lines no longer protected `<scheme>` from being parsed as an HTML tag.

## Learning

Keep any inline code span that contains `<…>` on one source line, even if that makes the
line longer than the wrap width. Build the docs site locally before pushing spec
documents (`bun run --cwd docs docs:build`), because markdownlint doesn't catch this.

## Action

The two spans were joined onto one line each (`420df50`). The docs build is a step in
the testing plan's documentation activity.
