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
  events. `tiny-harness tui --url <server>` starts it; bare `tiny-harness` starts it
  hosting the harness from the default configuration.
- The TUI SHALL show `STATE · sub-state` in the top bar (e.g. `INPUT_REQUIRED ·
  awaiting-next-message`), bind `ctrl+d` to Complete and `ctrl+c` to Cancel (both in the
  footer, acting only on a non-terminal task, otherwise a notice), offer inline `/`
  completion from the card's commands with their descriptions under the composer, list
  sub-tasks in the Task tab (`enter` opens one, `f4` returns to the parent), and follow
  the open task's `SubscribeToTask` stream once a message's own stream ends, so a reply
  from another surface and each sub-task row's state (relayed by the parent) show
  without a reload or polling. A sub-task is read once for its row's goal and followed
  only when opened. Conversation entries render as plain text (no Rich markup).
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
- The web renderer SHALL show a state badge and, while `INPUT_REQUIRED`, a sub-state
  badge; a **Complete** (primary) and a **Cancel task** (ghost) button, disabled when the
  task is terminal or none is open; a "← Parent" link on a sub-task; sub-task rows that
  open `?task=<id>` in place; and, when the composer starts with `/`, a WAI-ARIA
  combobox listbox of the card's commands (arrows move, Tab or Enter accepts, Escape
  closes). `?fixture=controls` runs it against a scripted harness for the visual tests.
- WHEN two surfaces are connected to one task THEN both SHALL receive the same updates,
  completion and cancellation included.
- `Modality` SHALL include `image` and `audio`; a `RenderItem` of kind `media` carries the
  `url` and `name` of an image or audio file. A renderer that cannot show a received
  media type SHALL show the placeholder naming it.
- `/attach <path>` SHALL be a surface command (`CommandSpec.runs_on = "surface"`, listed
  in the card with `runsOn`): the TUI runs it locally, the web renderer opens its file
  picker, and the server answers a client that sends it anyway with "this client cannot
  attach files". Every control that needs a media service SHALL be hidden or disabled
  unless the card's media extension says the service is on.
- The TUI SHALL attach files with `/attach` as chips above the composer (`Backspace` on an
  empty composer removes the last), checked against the card's types and limits, and send
  them as `raw` file parts. It SHALL show an image inline with `textual-image` WHERE that
  extra is installed and the terminal answers a kitty-graphics or sixel query, else one
  line with the name, the size and the path of a copy under
  `~/.cache/tiny-harness/media/<task_id>/<media_id><ext>` (directory `0700`, written with
  `O_NOFOLLOW | O_EXCL` and `os.replace`, ids validated). Audio entries show their
  transcript; a WAV entry (`⏎ to play`) plays on `Enter`, and any other audio type
  (`⏎ saves`) is saved to that cache on `Enter` and its entry then reads
  `saved to <path>`.
- Each surface SHALL fetch an image, an audio file or a spoken reply only when its URL is
  exactly `<agent><mediaPath>/<task_id>/<media_id>` on the agent's origin (no query or
  fragment, ids matching `[A-Za-z0-9_-]{1,128}`) and `task_id` is the task on screen
  (critic 8): the TUI's `pinned_media_ids` and the web's `mediaRoute` with
  `HarnessClient.getMedia(url, taskId)`. Any other URL shows "not a medium of this task"
  and is never fetched, played or replayed.
- The TUI SHALL record a voice turn while Space is held on an empty composer (a
  `HoldDetector` over auto-repeat: a second Space within `--hold-ms`, default 600 ms,
  starts the hold, a 0.25 s gap ends it; a lone Space types a space), and with `F5` as a
  toggle; `Escape` discards a recording or stops a spoken reply, and starting a recording
  or sending a message also stops it (R4.3, both surfaces); `F6` turns spoken replies
  on (off at start), sent as the message's `speak`. The `Recorder` captures 16 kHz mono
  WAV through `sounddevice` and discards a recording shorter than 0.3 s or silent; the
  `PcmPlayer` plays the speech stream as it arrives, with a speaking line that `Enter`
  replays. WITHOUT the `voice` extra, PortAudio or a device the TUI SHALL say "voice
  input unavailable: install tiny-harness[voice] (PortAudio)" (or "voice output …") and
  typing SHALL keep working.
- The web renderer SHALL attach files by a paperclip picker, by drop on the composer and
  by pasting an image, show them as removable chips, and send them as `raw` file parts.
  `MediaItem` SHALL fetch media with `X-Participant-Id` into a blob URL and render only
  accepted raster images and audio through `<img>` / `<audio>` (never SVG, never
  `innerHTML`); images fit the column and open full size in a dialog. An image SHALL be
  fetched only once it comes within three screenfuls of the conversation's visible part
  (an `IntersectionObserver`; at once where there is none). The `MediaCache` SHALL bound
  its memory: it streams each download against the card's `maxFileBytes` and stops it
  beyond, runs at most four downloads at once and queues the rest, keeps its blobs
  least-recently-used under 200 MiB (an evicted blob URL is revoked and fetched again
  when needed), and aborts every outstanding download when the task view closes.
- The web `MicButton` SHALL record while held (pointer) and toggle with `Space` or
  `Enter`, with `aria-pressed`, the name "Hold to talk" and a live region announcing
  "Recording", "Sent" and "Nothing recorded"; a generation counter stops every track of a
  microphone stream granted after the user let go. The speaker toggle (on by default)
  sets `speak`; `PcmStreamPlayer` schedules the PCM stream on Web Audio as it arrives,
  in buffers of at most 0.5 s, reads no further while more than 2 s is scheduled ahead
  of the playhead, and disconnects each buffer once it has played; the speech line offers Stop while it plays and Replay after it ends, stops or is
  interrupted. Starting a recording stops the reply being spoken.

## Design

[design.md § Surfaces and renderers](../specs/issue-3/design.md#surfaces-and-renderers-r20--interaction-rendererswebb),
[design.md § UI/UX design](../specs/issue-3/design.md#uiux-design) and the prototypes
under `docs/specs/issue-3/design/`.
[issue-38 design.md § TUI](../specs/issue-38/design.md#components-interfaces), [§ Web renderer](../specs/issue-38/design.md#components-interfaces) and the prototypes under `docs/specs/issue-38/design/`.

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | A2UI 0.9.1, surface and renderer entities, the Textual TUI (Layer 7); the web renderer (Layer 8) | [spec](../specs/issue-3/), [PR #13](https://github.com/MadaraUchiha-314/tiny-harness/pull/13), [PR #14](https://github.com/MadaraUchiha-314/tiny-harness/pull/14) |
| issue-20 | The TUI asserts a participant (`--participant`, else the OS user name) so it can send at all | [spec](../specs/issue-20/), [PR #21](https://github.com/MadaraUchiha-314/tiny-harness/pull/21) |
| issue-25 | TUI and web Complete/Cancel controls, the sub-state in the top bar and badge, `/` command completion, sub-task open and back; bare `tiny-harness` opens the TUI | [spec](../specs/issue-25/), [PR #26](https://github.com/MadaraUchiha-314/tiny-harness/pull/26), [decision-007](../decisions/decision-007.md) |
| issue-38 | Image and audio modalities; `/attach` as a surface command; attachments, inline media, hold-to-talk and spoken replies in the TUI (`voice` and `images` extras) and the web renderer | [spec](../specs/issue-38/), [PR #39](https://github.com/MadaraUchiha-314/tiny-harness/pull/39) |
