---
type: evidence
workItem: issue-38
---

# Documentation: multi-modal input and output, with a voice mode, in the TUI and the web renderer

## Capability docs

| Capability doc | What changed | History row |
|----------------|--------------|-------------|
| `docs/capabilities/media.md` | New: media by reference, the accepted types, `MediaIntake` and `guard`, `FileMediaStore` and fenced growing objects, the effective capabilities, the media route, the request cap, retention, spans | issue-38 |
| `docs/capabilities/models.md` | Media content parts and each adapter's mapping; `input_modalities`, `output_modalities`, `audio_input_formats`; the speech and image entities, their OpenAI implementations and fakes | issue-38 |
| `docs/capabilities/tools.md` | The `generate_image` intrinsic and the `media` content part | issue-38 |
| `docs/capabilities/surfaces-and-renderers.md` | Image and audio modalities; `/attach` as a surface command; attachments, inline media, hold-to-talk, spoken replies and the extras in the TUI; attach, `MediaItem`, `MicButton`, speaker toggle and the speech line in the web renderer | issue-38 |
| `docs/capabilities/demo.md` | `examples/multimodal` and `tests/e2e/test_demo_multimodal.py` | issue-38 |
| `docs/capabilities/configuration.md` | The four media sections, the new `[openai]` and `[retention]` keys, the seams on `Harness` and `build_runtime`, `tui --hold-ms` | issue-38 |
| `docs/capabilities/durable-execution.md` | Media references in history, `transcribe`, `open_speech`, `speak`, speech jobs drained at rollover and completion | issue-38 |
| `docs/capabilities/observability.md` | The `transcribe`, `speech`, `image` and `media.intake` spans | issue-38 |
| `docs/capabilities/a2a-server.md` | Intake in `execute`, the media route, the card's media modes and the media extension, `runsOn` | issue-38 |
| `docs/capabilities/persistence.md` | `[retention] media`, the sweep and purge of a task's media | issue-38 |
| `docs/capabilities/entities-and-registry.md` | The four new entity kinds | issue-38 |
| `docs/capabilities/context-window.md` | Media in the turn, in the token estimate and in compaction summaries | issue-38 |
| `docs/capabilities/capabilities.md` | Index row for `media`; the `models` and `demo` rows widened | (index, no history table) |
| `docs/architecture/architecture.md` | `harness/media/` and the `media` capability in the module table | (index, no history table) |
| `docs/decisions/decision-010.md` | New decision: media by reference, bytes in one task-scoped store, speech over the media route | — |
| `docs/decisions/decisions.md` | Index row for decision-010 | — |

## Documentation

| Document | What changed |
|----------|--------------|
| `docs/configuration/media.md` | New page "Images and voice": `[media]`, `[speech_to_text]`, `[text_to_speech]`, `[image_generation]`, `[openai] input_modalities` and `audio_tokens_per_second`, with defaults and the errors that stop the start |
| `docs/configuration/index.md` | The sections table names the media sections and links the new page |
| `docs/configuration/models.md` | The two new `[openai]` keys in the table, linked to the media page |
| `docs/configuration/storage.md` | The `media/` folder beside the store and `[retention] media`; a task's media goes with the task |
| `docs/cli/tui.md` | `/attach`, `F5`, `F6`, `Escape`, hold `Space`, `--hold-ms`; section "Images and voice" with a four-step start, the extras and PortAudio, the image fallback line and the "voice unavailable" messages |
| `docs/cli/index.md` | Next step: images and voice |
| `docs/sdk/example-multimodal.md` | New page "Example: images and voice": run the multimodal demo, the scenario, the web and TUI controls, the flow of a voice message, the files |
| `docs/sdk/extend.md` | Section "Use your own media services": the `speech_to_text=`, `text_to_speech=`, `image_generator=` and `media_store=` seams on `Harness` and `build_runtime`, with an example |
| `docs/sdk/index.md` | Next step: the multimodal example |
| `docs/.vitepress/config.mts` | Sidebar entries for the two new pages |
| `README.md` | Documentation table row for images and voice |
| `examples/multimodal/README.md` | New: how to run the demo and the scenario |
