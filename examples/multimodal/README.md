# tiny-harness multi-modal demo

The agent is an interior design helper. Show it a photo of a room. Ask it a question by
text, in an audio file or by voice. It answers by text and by voice, and it draws mock-ups
of the changes it suggests.

The demo uses an embedded Temporal and OpenAI. The only secret is `OPENAI_API_KEY`.

```bash
export OPENAI_API_KEY="$(secret-tool lookup service openai project tiny-harness)"
bun install --cwd renderers/web && bun run --cwd renderers/web build
uv run python -m examples.multimodal      # server + worker, web renderer at /ui
```

Open <http://127.0.0.1:8080/ui/> in a browser, or start the TUI in a second terminal:

```bash
uv sync --extra voice --extra images      # microphone, speaker and inline images
uv run tiny-harness tui --url http://127.0.0.1:8080
```

The TUI `voice` extra needs PortAudio from your system (for example, the `portaudio`
package). Without the extras, the TUI shows images as a saved file path, and the voice
keys say what to install.

## The scenario

Use the files in `fixtures/`. They are synthetic: OpenAI made the photo and spoke the two
recordings, so no person's photo or voice is in the repository.

1. Attach `fixtures/room.jpg` and ask "Describe this room."
2. Attach `fixtures/question.wav`. It asks which wall colour makes the room brighter.
3. Hold to talk and ask for a mock-up of the room with that colour. In the web renderer,
   hold the microphone button. In the TUI, hold Space on an empty input, or press F5 to
   start and F5 to stop. The agent speaks its reply and shows a generated image.
4. Type "Now make the sofa in the first photo green, and show me." The agent goes back to
   the first photo and draws a new mock-up.

To attach a file in the TUI, type `/attach examples/multimodal/fixtures/room.jpg`. In the
web renderer, use the paperclip button, drop the file on the input, or paste an image.

## What is in this directory

| Path | What it does |
|------|--------------|
| `config.toml` | Embedded Temporal, OpenAI `gpt-6.1-sol`, speech-to-text `gpt-4o-mini-transcribe`, text-to-speech `gpt-4o-mini-tts` (voice `coral`), images `gpt-image-2` |
| `plugin.json` and `io.github.madarauchiha-314.tiny-harness/prompts/rules.md` | The plugin. Its prompt makes the agent an interior design helper that calls `generate_image` when you ask to see a change |
| `fixtures/` | The photo and the two recordings. `fixtures/generate.py` makes new ones with OpenAI |
| `__main__.py` | Loads the configuration file and starts the server with the worker in the same process |

The demo keeps its state (store, media, trace, embedded Temporal) in
`examples/multimodal/.state/`. Remove that directory to start again.

`tests/e2e/test_demo_multimodal.py` runs the same scenario through the A2A client. It
reads the spoken reply through the media route and records how soon the first audio
arrives after the reply text. It skips when `OPENAI_API_KEY` is not set.
