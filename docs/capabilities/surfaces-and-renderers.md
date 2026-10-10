# Capability: surfaces-and-renderers

> A terminal and a web page on one harness instance at the same time, both A2A clients
> and nothing else, both rendering the A2UI 0.9.1 basic catalog and sending its actions
> back.

## What it is

Where a user meets the harness. The surface and renderer entities describe what can be
drawn; the A2UI extension is how the agent draws it; the TUI (Textual) and the web
renderer (React 19 on the official A2UI renderer) are the two implementations. Lives in
`tiny_harness/interaction/` and `renderers/web/`.

## Current behaviour

- A surface SHALL declare its modality (text only) and renderer capabilities; a renderer
  SHALL declare which message and artifact kinds it renders, with MCP Apps
  (`text/html;profile=mcp-app`) declarable later without an interface change.
- The harness SHALL implement the A2UI A2A extension at 0.9.1
  (`https://a2ui.org/a2a-extension/a2ui/v0.9.1`; the 1.0 SDKs were not available),
  advertising the basic catalog id and `acceptsInlineCatalogs: false` in the card. The
  schemas are vendored under `tiny_harness/interaction/a2ui/schemas/` with attribution.
- `emit_ui` SHALL validate the server messages against the schemas and emit them as a
  `TaskArtifactUpdateEvent` named `a2ui` with `application/a2ui+json` parts; the
  workflow records the surfaces and components the task created.
- WHEN a user action arrives as a message with an `application/a2ui+json` part THEN
  intake SHALL validate it against the task's surface registry and discard an action
  naming a surface or component the task did not create; a genuine action resumes the
  task with `[A2UI action] <name> on surface <id> from <component>` and its context.
- Both renderers SHALL render every component of the basic catalog (Text, Image, Icon,
  Video, AudioPlayer, Row, Column, List, Card, Tabs, Divider, Modal, Button, CheckBox,
  TextField, DateTimeInput, ChoicePicker, Slider); the TUI renders Video and AudioPlayer
  as the typed placeholder, and any kind a renderer cannot render SHALL be shown as a
  placeholder naming the kind, never dropped.
- The TUI SHALL be a Textual app with the conversation on the left, Task / Plan / Trace
  tabs on the right and the composer below, every action on a key; it streams the reply
  and keeps a `SubscribeToTask` stream per open task, so a second surface sees the same
  events. `tiny-harness tui --url <server>` starts it.
- The TUI SHALL assert a participant on every message and action it sends, as the
  `X-Participant-Id` header and the `participant_id` metadata: `--participant <id>`, else
  the OS user name. IF neither yields a non-empty printable-ASCII id (a blank
  `--participant`, no OS user name, or a non-ASCII or control character, which the
  header cannot carry intact) THEN `tiny-harness tui` SHALL exit 2 naming
  `--participant` before it connects. The
  composer shows the asserted id (`Enter to send as <id>`). The id is self-asserted
  (decision-003); the server's refusal of a message that asserts nobody is unchanged.
- The web renderer SHALL be a Vite + React 19 + TypeScript (strict) app on shadcn
  (Tailwind v4, the shadcn/ui primitives and the chat components `MessageScroller`,
  `Message`, `Bubble` and `Marker`) that reaches the server only through the official
  A2A JavaScript SDK (`@a2a-js/sdk`, protocol 1.0: card resolution, the JSON-RPC
  transport, `sendMessageStream`, `resubscribeTask`, `cancelTask`), adding
  `X-Participant-Id`, folds the SDK's events into a pure model, takes the harness URL
  from `?server=`, the browser's remembered choice or its own origin (a "Harness" field
  in the header changes it), attaches to an existing task with `?task=`, keeps a
  `SubscribeToTask` subscription open after a stream ends in a non-terminal state
  (reopened after a pause, since the SDK ends a stream at every final event) so a reply
  from another surface shows up, is published on the docs site under `/ui/` by the
  docs workflow, and
  renders cards with `@a2ui/react`'s `MessageProcessor` and the basic catalog; it is
  served under `/ui` when `ui_dir` points at its build and is covered by Playwright
  visual and axe-core accessibility tests.
- WHEN two surfaces are connected to one task THEN both SHALL receive the same updates.

## Design

[design.md § Surfaces and renderers](../specs/issue-3/design.md#surfaces-and-renderers-r20--interaction-rendererswebb),
[design.md § UI/UX design](../specs/issue-3/design.md#uiux-design) and the prototypes
under `docs/specs/issue-3/design/`.

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | A2UI 0.9.1, surface and renderer entities, the Textual TUI (Layer 7); the web renderer (Layer 8) | [spec](../specs/issue-3/), [PR #13](https://github.com/MadaraUchiha-314/tiny-harness/pull/13), [PR #14](https://github.com/MadaraUchiha-314/tiny-harness/pull/14) |
| issue-20 | The TUI asserts a participant (`--participant`, else the OS user name) so it can send at all | [spec](../specs/issue-20/), [PR #21](https://github.com/MadaraUchiha-314/tiny-harness/pull/21) |
