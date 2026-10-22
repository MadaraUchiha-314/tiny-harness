---
type: testing-plan
phase: test-planning
workItem: issue-38
status: approved
approvedBy: ["MadaraUchiha-314"]
overrides: {}
---

<!-- Written per the `the-loop:writing` skill: front-load each section's
     conclusion, draw it rather than describe it (3+ named parts -> a mermaid
     diagram), and keep the formal registers formal (EARS, abuse cases,
     RFC-2119, API contracts, schema descriptions). -->

# Testing plan: multi-modal input and output, with a voice mode, in the TUI and the web renderer

> Derived from the approved [`requirements.md`](requirements.md) and
> [`design.md`](design.md), **before** `tasks.md`. Authored at `test-planning`, completed at
> `verification`.
>
> **This file is executable content.** It names commands an agent will run. Credentials
> appear by reference only.

**Most of the proof runs with fakes; one e2e test spends real OpenAI calls.** Every
provider interface has a scripted fake (`FakeLLM`, `FakeSpeechToText`,
`FakeTextToSpeech`, `FakeImageGenerator`), so the workflow, the media store, the route,
both surfaces and every abuse case are proved offline on the Temporal dev server. The
demo e2e test (T4) then runs R7.2 against OpenAI once. Microphone and speaker hardware
are not testable in CI; the recorder and player are tested against injected audio
devices, and the real hardware is a manual row (T14).

## Test matrix

| # | Type | Applies? | Scope / what it proves | Where it runs |
|---|------|----------|------------------------|---------------|
| T1 | Unit | yes | `sniff` (each accepted type; each forged, truncated, oversized-header and bomb file; MP3 frame walk, MP4 `stts` sum, Ogg granule walk, WebM cluster walk without `Duration`; hop budget); `MediaIntake` rules and all-or-nothing rollback; `FileMediaStore` (atomic `put`, id validation, generations and fencing, `read_stream` end / failed / interrupted / idle, `sweep`, `delete_task`); `MediaAttachment` refusing to serialise with `data`; `media.capabilities`; `guard` modes; adapter content mapping per row of the design's table (golden request bodies) and **text-only requests byte-identical to 0.8.0**; `context._chars` for image, transcript and native audio; compaction media lines and the missing-line fallback; `speakable_text`; OpenAI STT/TTS/image adapters against `respx` (request shape, `base_url` only, error mapping, `max_retries=0`); config validation (`[media]` required by the other three, provider key rule, effective request cap); `CommandSpec.runs_on` and the server's reply to a surface command; `HoldDetector` timing with a fake clock (lone press, hold, release by gap, release event, `--hold-ms`); `Recorder` minimum length and silence discard on an injected stream; `PcmPlayer` feeding an injected output | `uv run pytest tests/unit` |
| T2 | Integration (scenario) | yes | Over the Temporal dev server with the fakes, Gherkin-documented: the scenarios listed in the trace below — image to model, voice turn, native audio, model without images, no STT, generated image and back-reference, compaction naming media, worker restart with media and mid-speech, speech job drained at rollover and at completion, speech cancelled on cancel, the event order (speech artifact before the final status), generation fencing seen by a reader. A2A-level tests use the real server over loopback (`streaming_asgi.py`), because `httpx.ASGITransport` buffers open streams | `uv run pytest tests/integration/media` |
| T3 | Contract | yes | `settings.schema.json` gains `[media]`, `[speech_to_text]`, `[text_to_speech]`, `[image_generation]`, `[openai] input_modalities` and `audio_tokens_per_second`, `[retention] media`; the agent card snapshot gains the effective modes and the media extension **only** when `[media]` is set (unchanged otherwise); new extension schema `docs/a2a/ext/media.json` validates the card params and the part/message metadata; `docs/a2a/ext/intrinsics/generate_image.json`; the commands extension gains optional `runsOn`; public-API snapshots of `tiny_harness.harness.models`, `tiny_harness.harness.media`, `tiny_harness.service`, `tiny_harness.config`, `tiny_harness.interaction` gain exactly the design's names | `uv run pytest tests/contract` |
| T4 | End-to-end | yes | `tests/e2e/test_demo_multimodal.py`: `examples/multimodal` on embedded Temporal with OpenAI (`gpt-6.1-sol`, `gpt-4o-mini-transcribe`, `gpt-4o-mini-tts`, `gpt-image-2`) driven through the A2A client with the committed fixtures: the photo, the audio file, a voice turn, a spoken streamed reply read through the media route (first chunk timed), a generated image fetched and checked as PNG, and the back-reference turn. Asserts states, artifacts, transcript, that the streamed PCM is non-empty and well-formed, and no secret, base64 or media bytes in the trace or log. Skips naming `OPENAI_API_KEY` when absent | `uv run pytest tests/e2e/test_demo_multimodal.py` |
| T5 | UI / visual | yes | Web: Playwright `visual` project gains fixture states matching the locked prototype — pending chips, image and audio in turns, transcript, recording (mic pressed, meter), speaking marker with Stop, interrupted with Replay, agent image, rejection error — light, dark and phone. TUI: `tests/ui/test_tui_keys.py` drives `/attach`, chip removal, hold-Space (fake clock), `F5`, `F6`, `Escape` with `ScriptedClient` and fake audio devices | `cd renderers/web && bun run build && bun x playwright test --project=visual`; `uv run pytest tests/ui` |
| T6 | Snapshot | yes | TUI SVG snapshots (`pytest-textual-snapshot`): chips, image fallback line, recording bar, transcript, speaking line, rejection. Web unit snapshots are not used; the visual row covers rendering | `uv run pytest tests/ui/test_tui_snapshots.py` |
| T7 | Performance | yes (narrow) | NFR latency: in T4, time from the reply text's final status to the first PCM chunk at the client, recorded (target ≤ 1.5 s, reported, not a CI gate because it depends on OpenAI). Offline: `read_stream` delivers an appended chunk within 2 × `poll` (unit). Size: a 20 MiB image goes through intake, store and route in the integration run without exceeding the request cap | (inside T1, T2, T4) |
| T8 | Security / abuse case | yes | Every row of the design's abuse-case table: oversize file and message (413 and `InvalidParams`, nothing stored); SVG, mismatched and HTML-named-PNG refused; `url` file part refused with **no outbound request** (`respx` asserts none); a `control` carrying a file part refused; push and remote-agent file parts dropped; another participant's and another task's media → 404; traversal ids → 404; route headers (`nosniff`, CSP, `Content-Disposition`); a transcript asking for a tool outside the allow-list gets nothing new; decompression-bomb PNG refused before decode; no media bytes or base64 in trace or log; `MediaAttachment` with `data` not serialisable; TUI cache write refuses a planted symlink; web `MediaItem` refuses SVG; mic late-grant race stops the tracks (web unit, fake `getUserMedia`) | `uv run pytest tests/security/test_media.py`; `cd renderers/web && bun run test` |
| T9 | Accessibility | yes | axe on the new web states (`a11y` project): mic button name, `aria-pressed`, live-region announcements, chip remove buttons, image alt text, keyboard-only flow (attach via keyboard, toggle mic with Space/Enter, Stop, Replay) | `cd renderers/web && bun x playwright test --project=a11y` |
| T10 | Migration / upgrade | yes (narrow) | A 0.8.0 workflow history and stored `AgentState` (fixtures recorded from `main`) replay and deserialise unchanged — `MessageItem.media`, `LLMModelInfo` fields and `IntakeOut.media` are additive with defaults; a config without `[media]` gives a card identical to 0.8.0's snapshot. No store schema migration (media is a new directory) | `uv run pytest tests/integration/media/test_compat.py` |
| T11 | Back compatibility (regression) | yes | The whole existing suite passes. Changes to existing tests are limited to the `send(text)` → `send(parts)` signature in the TUI client fixtures and are listed in the evidence | `uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui` |
| T12 | Packaging | yes | The wheel installs and the server runs without the `voice` and `images` extras; the TUI starts without them and shows the "install tiny-harness[voice]" reason; with `tiny-harness[voice,images]` both import. Extends `tests/integration/test_package.py` | `uv run pytest tests/integration/test_package.py` |
| T13 | Static | yes | ruff, pyright strict, markdownlint over all files, the web type-check, as CI | `uv run pre-commit run --all-files`; `cd renderers/web && bun run typecheck` |
| T14 | Manual exploratory | yes | On this machine with a microphone and speakers: run `python -m examples.multimodal`, then (a) the web UI in Chromium and Firefox — attach by picker, drop and paste; hold the mic, speak, release; hear the reply stream; Stop; Replay; (b) the TUI in kitty (inline image, release events) and in a terminal without graphics (path line, auto-repeat hold) — `/attach`, hold Space, `F5`, `F6`, `Escape`. Confirms the real microphone and audio paths CI cannot reach | manual, per `examples/multimodal/README.md` |
| T15 | Docs build | yes | New pages (media configuration, voice in the TUI, the multimodal example, the media extension) and changed capability docs build and lint | `cd docs && bun run docs:build` |

## Scenarios & requirement trace

| Row | Requirement(s) | Scenario / case |
|-----|----------------|-----------------|
| T1 | R1.4, R1.5, abuse 1–3, 7 | `sniff` and `MediaIntake` cases per type and per forgery |
| T1 | R5.1, R5.2, R5.6 | adapter golden bodies; text-only byte-identical; `media.capabilities` |
| T1 | R5.3–R5.5, R5.7 | OpenAI media adapters against `respx`; config validation |
| T1 | R3.2, R3.3, R3.6 | `HoldDetector`; `Recorder` discard |
| T2 | R1.3, R1.6, R6.1 | `Scenario: an image and a question reach the model` |
| T2 | R1.7 | `Scenario: a model without image input gets a note and the task continues` |
| T2 | R3.4, R4.1, R4.2 | `Scenario: a voice turn is transcribed, answered and spoken` |
| T2 | R3.4 | `Scenario: native audio skips speech-to-text` |
| T2 | R1.6 | `Scenario: audio with no speech-to-text configured gets a note` |
| T2 | R2.1, R2.2, R2.5 | `Scenario: generate_image shows an image and a later turn sees it` |
| T2 | R6.2 | `Scenario: compaction names every media item` |
| T2 | R6.4, NFR durability | `Scenario: media survives a worker restart` |
| T2 | R4.2 | `Scenario: a retry during speech starts a new generation and the reader is told` |
| T2 | R4.2 | `Scenario: the speech artifact arrives before the final status` |
| T2 | R4.3, R4.5 | `Scenario: speech that fails leaves the text and a note` |
| T2 | R4 | `Scenario: rollover and completion wait for speech; cancel stops it` |
| T2 | R6.3 | `Scenario: media sent from one surface is fetched by another participant on the task` |
| T3 | R5.5, R5.6 | card snapshot with and without `[media]`; media extension schema |
| T4 | R7.1–R7.3, NFR latency | demo scenario end to end |
| T5, T6 | R1.1, R1.2, R2.3, R2.4, R3.1–R3.3, R3.5, R4.3, R4.4, R8 | prototype states on both surfaces |
| T8 | abuse 1–8, design critic 5, 8, 10 | the design's abuse-case table |
| T9 | NFR accessibility | axe + keyboard flow |
| T10 | NFR, R5 | 0.8.0 replay and card identity |
| T14 | R3, R4, R8 on real devices | manual run |
| T15 | R7.4 | docs build |

R9 (the module and interface inventory) is proved by the design-approval gate, not by a
test.

## Verification environment

- **Repositories:** this repository only, branch `issue-38-multimodal`.
- **Services:** the Temporal dev server, started by the tests through `start_local`
  (downloaded once into the uv cache); T4 uses the demo's embedded mode. Nothing else to
  bring up.
- **HTTP:** A2A-level tests serve the app with uvicorn on `127.0.0.1` and an ephemeral port;
  `tests/integration/streaming_asgi.py` where a stream must stay open.
- **Fixtures & data:** `tests/fixtures/media/` — one small valid file per accepted type,
  forged files (SVG named `.png`, HTML named `.png`, PNG declared JPEG, a 100 KB PNG
  declaring 50 000 × 50 000, an MP4 with a video track, a WebM with a video track, a
  low-bitrate MP3 over the duration cap, an Ogg with a lying last granule, truncated
  files); 0.8.0 history and state fixtures for T10; the demo's `room.jpg`,
  `question.wav` and `followup.wav` (generated by TTS, so no personal voice is
  committed). Audio devices are injected fakes in T1/T5.
- **Credentials:** `OPENAI_API_KEY` for T4 and T14 only, from the environment, never
  written down.
- **Bring-up:** `uv sync --locked --all-extras` (the `voice` and `images` extras for the
  TUI tests; PortAudio from the system package `portaudio`) and `cd renderers/web && bun
  install --frozen-lockfile && bun x playwright install chromium`.
- **Tear-down:** none; `tmp_path` and the tests' context managers stop servers and remove
  files.
- **Temp space:** if `/tmp` is full, set `TMPDIR` under `~/.cache` and pass pytest
  `--basetemp` there.
- **If bring-up fails:** record it under Verification results, leave the dependent rows
  unticked, and escalate on PR #39. T4 without `OPENAI_API_KEY` is recorded as skipped,
  not passed.

## Evidence plan

| Row | Evidence | Path under `evidence/` |
|-----|----------|------------------------|
| T1 | test summary (counts, duration) | `unit.md` |
| T2 | `the-loop scenarios --format markdown` table + run output | `integration.md` |
| T3 | run output; card snapshot diff | `contract.md` |
| T4 | run output, the measured first-chunk latency, the generated image, a 5 s excerpt of the spoken reply as WAV | `e2e.md`, `e2e/generated.png`, `e2e/reply-excerpt.wav` |
| T5 | screenshots of each web state (light, dark, phone); a GIF of the hold-to-talk → transcript → speaking flow | `ui/web-<state>.png`, `ui/web-voice-flow.gif` |
| T6 | TUI SVG snapshots rendered to PNG | `ui/tui-<state>.png` |
| T7 | latency numbers | `e2e.md` § Latency |
| T8 | run output, one section per abuse case | `security.md` |
| T9 | axe results | `a11y.md` |
| T10, T11, T12 | run output | `regression.md`, `packaging.md` |
| T13 | run output | `static.md` |
| T14 | what was tried, on which terminal and browser, and what was seen; screenshots of the kitty inline image and the fallback line; a GIF of the web voice flow on a real microphone | `manual.md`, `manual/*.png`, `manual/*.gif` |
| T15 | build output | `docs.md` |

Redaction: no committed audio carries a person's voice (fixtures and the excerpt are
synthetic); logs are checked for `OPENAI_API_KEY`, bearer tokens and hostnames other than
`127.0.0.1` before commit.

## Verification activities

- [ ] T1 — `uv run pytest tests/unit`
- [ ] T2 — `uv run pytest tests/integration/media`
- [ ] T3 — `uv run pytest tests/contract`
- [ ] T4 — `uv run pytest tests/e2e/test_demo_multimodal.py` (with `OPENAI_API_KEY`)
- [ ] T5 — `cd renderers/web && bun run build && bun x playwright test --project=visual`; `uv run pytest tests/ui/test_tui_keys.py`
- [ ] T6 — `uv run pytest tests/ui/test_tui_snapshots.py`
- [ ] T7 — latency recorded from the T4 run
- [ ] T8 — `uv run pytest tests/security/test_media.py`; `cd renderers/web && bun run test`
- [ ] T9 — `cd renderers/web && bun x playwright test --project=a11y`
- [ ] T10 — `uv run pytest tests/integration/media/test_compat.py`
- [ ] T11 — `uv run pytest tests/unit tests/integration tests/contract tests/security tests/ui`
- [ ] T12 — `uv run pytest tests/integration/test_package.py`
- [ ] T13 — `uv run pre-commit run --all-files`; `cd renderers/web && bun run typecheck`
- [ ] T14 — manual run per `examples/multimodal/README.md`
- [ ] T15 — `cd docs && bun run docs:build`

## Verification results

_Not yet executed._

| Activity | Command / procedure | Outcome | Evidence |
|----------|--------------------|---------|----------|
| | | | |

## Review comments

> Appended by the-loop's `record-feedback` hook when a human gate approves with
> comments (issue-109). Append-only and attributed: an approval never silently
> discards a reviewer's suggestions, and the feedback travels with the document
> it concerns rather than living in a side-channel tracker.

### 2026-10-22 — approved

**@MadaraUchiha-314** wrote:

approved
