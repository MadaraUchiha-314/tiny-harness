# T1 — unit tests

Work item issue-38, activity T1 (and the offline half of T7: `read_stream` delivers an
appended chunk within 2 × `poll`, in `tests/unit/media/test_store.py`).

2026-10-22, branch `issue-38-multimodal` at `8d924e3`, Python 3.14.7,
`uv sync --locked --all-extras`.

## `uv run pytest tests/unit`

```text
1033 passed in 11.44s
exit=0
```

## New unit tests for issue-38

| Tests | File | Covers |
|------:|------|--------|
| 41 | `tests/unit/media/test_sniff_images.py` | `sniff` per image type; forged, truncated, oversized-header and bomb files |
| 44 | `tests/unit/media/test_sniff_audio.py` | MP3 frame walk, MP4 `stts` sum, Ogg granule walk, WebM cluster walk, hop budget |
| 23 | `tests/unit/media/test_intake.py` | `MediaIntake` rules, all-or-nothing rollback |
| 25 | `tests/unit/media/test_store.py` | `FileMediaStore`: atomic `put`, id validation, generations and fencing, `read_stream` end / failed / interrupted / idle, `sweep`, `delete_task` |
| 20 | `tests/unit/media/test_models.py` | `MediaAttachment` refuses to serialise with `data` |
| 13 | `tests/unit/media/test_capabilities.py` | `media.capabilities` |
| 17 | `tests/unit/media/test_speakable.py` | `speakable_text` |
| 26 | `tests/unit/models/test_media_content.py` | adapter content mapping (golden bodies); text-only requests byte-identical to 0.8.0 |
| 34 | `tests/unit/models/test_openai_media.py` | OpenAI STT / TTS / image adapters against `respx` |
| 8 | `tests/unit/models/test_speech_fakes.py` | the scripted fakes |
| 8 | `tests/unit/core/test_context_media.py` | `context._chars` for image, transcript, native audio |
| 8 | `tests/unit/core/test_compaction_media.py` | compaction media lines, missing-line fallback |
| 4 | `tests/unit/core/test_generate_image.py` | the `generate_image` intrinsic |
| 25 | `tests/unit/test_config_media.py` | `[media]` required by the other three, provider key rule, effective request cap |
| 6 | `tests/unit/commands/test_surface_commands.py` | `CommandSpec.runs_on`, the server's reply to a surface command |
| 6 | `tests/unit/interaction/test_plan_media.py` | media in the interaction plan |
| 7 | `tests/unit/o11y/test_media_spans.py` | media spans carry no bytes |
| 3 | `tests/unit/service/test_retention_media.py` | `[retention] media` |
| 6 | `tests/unit/test_example_multimodal.py` | the multimodal example's config |
| 7 | `tests/unit/tui/test_hold_detector.py` | `HoldDetector` with a fake clock |
| 4 | `tests/unit/tui/test_recorder.py` | `Recorder` minimum length and silence discard |
| 4 | `tests/unit/tui/test_pcm_player.py` | `PcmPlayer` on an injected output |
| 4 | `tests/unit/tui/test_client_media.py` | TUI client media send |

Total new: 373 tests in 23 files. Changed existing unit files: `entities/test_ref.py`,
`service/test_a2a_units.py`, `service/test_cli.py`, `test_layout.py`.
