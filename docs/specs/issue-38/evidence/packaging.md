# T12 — packaging

Work item issue-38, activity T12. The wheel built from this checkout, installed into fresh
virtual environments.

2026-10-22, branch `issue-38-multimodal` at `22701e9`, Python 3.14.7. PortAudio is the
system package `portaudio`.

## `uv run pytest tests/integration/test_package.py -v`

```text
tests/integration/test_package.py::test_built_wheel_installs_and_exposes_the_version PASSED
tests/integration/test_package.py::test_the_fastapi_helper_needs_its_extra PASSED
tests/integration/test_package.py::test_the_server_and_the_tui_run_without_the_voice_and_images_extras PASSED
tests/integration/test_package.py::test_the_voice_and_images_extras_import PASSED
4 passed in 23.37s
exit=0
```

## What each new test proves

| Test | Proves |
|------|--------|
| `test_the_server_and_the_tui_run_without_the_voice_and_images_extras` | Installed without extras, `sounddevice` and `textual_image` do not import. `tiny-harness serve` with `[media]`, `[speech_to_text]`, `[text_to_speech]` and `[image_generation]` starts, and its card lists `image/png` and `audio/wav` input and the media extension. The TUI opens against an agent that accepts audio; F5 says `install tiny-harness[voice]`; there is no inline image view; a typed message still sends (R3.5) |
| `test_the_voice_and_images_extras_import` | Installed as `tiny-harness[voice,images]`, `textual_image` imports and `sounddevice` imports (PortAudio is present on this machine) (R8.1) |

The first two tests are the existing 0.8.0 packaging checks, unchanged.
