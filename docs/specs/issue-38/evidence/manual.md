# T14 — manual exploratory run (pending a human)

Work item issue-38, activity T14. **Not executed.** This file says why, what ran in its
place, and the steps a person follows to run it.

## Why it did not run

T14 needs a real microphone, real speakers, the kitty terminal and a person who speaks and
listens. The verification agent runs unattended and headless: it has no audio devices, it
cannot speak into a microphone or hear a reply, and it cannot judge what a terminal shows.
So T14 stays unticked in `testing-plan.md` until a person runs it and records the result
here.

## What ran in its place

These runs cover the same paths with injected or fake devices. They do not replace T14.

| Path | Substitute | Evidence |
|------|------------|----------|
| Web microphone: hold, record, release, send | Playwright Chromium with `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream` (a fake microphone that plays a beep) | [`ui.md`](ui.md), [`ui/web-voice-flow.gif`](ui/web-voice-flow.gif), [`a11y.md`](a11y.md) |
| Web spoken reply: stream, Stop, Replay, interrupted | `?fixture=media` with a scripted PCM stream, `--autoplay-policy=no-user-gesture-required` | [`ui.md`](ui.md) |
| Web microphone permission races | vitest with a fake `getUserMedia` | [`security.md`](security.md), design critic 10 |
| TUI recording and playback | `Recorder` and `PcmPlayer` on injected streams; `HoldDetector` on a fake clock; Pilot tests with fake audio devices | [`unit.md`](unit.md), [`ui.md`](ui.md) |
| TUI inline image and fallback line | Pilot tests with and without a graphics-capable terminal; SVG snapshots | [`ui.md`](ui.md) |
| The real OpenAI voice path | The e2e demo test with the committed synthetic recordings | [`e2e.md`](e2e.md) |

## Steps for the person who runs it

From `examples/multimodal/README.md`. Use a machine with a microphone and speakers.

1. Set `OPENAI_API_KEY` in the environment. Do not write it into a file in the repository.
2. Build the web renderer and start the demo:

   ```bash
   bun install --cwd renderers/web && bun run --cwd renderers/web build
   uv run python -m examples.multimodal
   ```

3. **Web, in Chromium and then in Firefox.** Open `http://127.0.0.1:8080/ui/`.
   1. Attach `examples/multimodal/fixtures/room.jpg` with the paperclip and ask
      "Describe this room." Do it again by dropping the file on the input, and by pasting
      an image.
   2. Attach `fixtures/question.wav`. Check that the transcript shows.
   3. Hold the microphone button, ask for a mock-up of the room in that wall colour, and
      release. Check: the recording indicator and meter, the transcript, the generated
      image, and that you hear the reply start soon after its text.
   4. Press Stop while it speaks. Then press Replay.
   5. Type "Now make the sofa in the first photo green, and show me."
4. **TUI in kitty.** In a second terminal:

   ```bash
   uv sync --extra voice --extra images
   uv run tiny-harness tui --url http://127.0.0.1:8080
   ```

   1. `/attach examples/multimodal/fixtures/room.jpg`, then Enter. Check that the image
      shows inline.
   2. On an empty input, hold Space, speak, and release. Then press F5 to start and F5 to
      stop. Press Escape during a recording to discard it.
   3. Press F6 to turn spoken replies on and off. Press Escape while a reply speaks.
5. **TUI in a terminal without graphics** (for example, a plain xterm). Repeat step 4.
   Check that each image shows as a saved-file path line, and that hold-Space works by
   key auto-repeat.

## What to record here

For each step: the browser or terminal and its version, what you did, and what you saw
or heard. Add screenshots of the kitty inline image and of the fallback line under
`manual/`, and a GIF of the web voice flow on the real microphone (`manual/*.gif`).
Remove personal data from the captures before you commit them.
