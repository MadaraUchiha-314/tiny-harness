# T2 — integration scenarios (media)

Work item issue-38, activity T2 (and the offline size half of T7). Over the Temporal dev
server (`start_local`) with the scripted fakes (`FakeLLM`, `FakeSpeechToText`,
`FakeTextToSpeech`, `FakeImageGenerator`); A2A-level tests serve the app with uvicorn on
`127.0.0.1` or through `tests/integration/streaming_asgi.py`.

2026-10-22, branch `issue-38-multimodal` at `ec5f6b8`, Python 3.14.7.

## `uv run pytest tests/integration/media -v`

```text
tests/integration/media/test_a2a_intake.py::test_a_file_without_media_is_refused_as_invalid_params PASSED
tests/integration/media/test_a2a_intake.py::test_an_oversized_file_is_refused_and_nothing_is_stored PASSED
tests/integration/media/test_a2a_intake.py::test_an_image_is_stored_before_the_turn_starts PASSED
tests/integration/media/test_a2a_intake.py::test_a_url_file_part_is_refused PASSED
tests/integration/media/test_compaction.py::test_compaction_names_every_media_item PASSED
tests/integration/media/test_compat.py::test_a_0_8_0_history_replays_unchanged PASSED
tests/integration/media/test_compat.py::test_a_0_8_0_agent_state_deserialises_unchanged PASSED
tests/integration/media/test_durability.py::test_media_survives_a_worker_restart PASSED
tests/integration/media/test_generate_image.py::test_generate_image_shows_an_image_and_a_later_turn_sees_it PASSED
tests/integration/media/test_generate_image.py::test_no_generate_image_tool_without_an_image_generator PASSED
tests/integration/media/test_history_media.py::test_media_sent_from_one_surface_is_fetched_by_another_participant PASSED
tests/integration/media/test_media_route.py::test_a_chunk_reaches_the_client_while_speech_is_written PASSED
tests/integration/media/test_media_route.py::test_a_failed_or_superseded_speech_aborts_the_stream[failed] PASSED
tests/integration/media/test_media_route.py::test_a_failed_or_superseded_speech_aborts_the_stream[new generation] PASSED
tests/integration/media/test_media_route.py::test_a_mounted_harness_serves_its_media_to_participants_only[starlette] PASSED
tests/integration/media/test_media_route.py::test_a_mounted_harness_serves_its_media_to_participants_only[fastapi] PASSED
tests/integration/media/test_media_route.py::test_route_options_turn_the_media_route_off PASSED
tests/integration/media/test_model_media.py::test_an_image_and_a_question_reach_the_model PASSED
tests/integration/media/test_model_media.py::test_a_model_without_image_input_gets_a_note_and_the_task_continues PASSED
tests/integration/media/test_size.py::test_a_20_mib_image_goes_through_intake_store_and_route PASSED
tests/integration/media/test_speech.py::test_a_voice_turn_is_transcribed_answered_and_spoken PASSED
tests/integration/media/test_speech.py::test_the_speech_artifact_arrives_before_the_final_status PASSED
tests/integration/media/test_speech.py::test_a_retry_during_speech_starts_a_new_generation_and_the_reader_is_told PASSED
tests/integration/media/test_speech.py::test_speech_that_fails_leaves_the_text_and_a_note PASSED
tests/integration/media/test_speech.py::test_rollover_and_completion_wait_for_speech_cancel_stops_it PASSED
tests/integration/media/test_speech.py::test_completion_waits_for_the_last_spoken_reply PASSED
tests/integration/media/test_speech.py::test_speech_still_running_when_the_drain_ends_is_stopped_with_a_note PASSED
tests/integration/media/test_transcribe.py::test_a_recording_is_transcribed_and_the_transcript_is_shown PASSED
tests/integration/media/test_transcribe.py::test_native_audio_skips_speech_to_text PASSED
tests/integration/media/test_transcribe.py::test_audio_with_no_speech_to_text_configured_gets_a_note PASSED
tests/integration/media/test_transcribe.py::test_a_failed_transcription_leaves_a_note_and_the_turn_continues PASSED
31 passed, 378 warnings in 24.07s
exit=0
```

The 378 warnings are the existing Temporal pydantic-converter `UserWarning` and one
`PytestWarning` (a sync test under the module's `asyncio` mark); none is new behaviour.

### Added during verification

The plan's T7 says "a 20 MiB image goes through intake, store and route in the
integration run without exceeding the request cap". No test did this, so verification
added `tests/integration/media/test_size.py` (commit `ec5f6b8`): a PNG of exactly
`max_file_bytes` (20 971 520 bytes) is sent base64 over JSON-RPC to a mounted agent on a
real loopback socket, is stored byte-for-byte, and the media route serves it back; a
body one byte over the effective request cap is answered 413 and nothing more is stored.
Mutation check: with `wrap_middleware(..., media=None)` in `Harness.asgi_app` the send
fails with `413 Content Too Large`; with the code restored it passes.

## Scenario table

`the-loop scenarios --root "$PWD" --glob 'tests/integration/media/*.py' --format markdown`

| # | Feature | Scenario | Requirement | Location |
|---|---|---|---|---|
| 1 | Media intake at the A2A server | a file sent to an agent without [media] is refused | — | tests/integration/media/test_a2a_intake.py:67 |
| 2 | Media intake at the A2A server | an oversized file is refused with its limit | — | tests/integration/media/test_a2a_intake.py:90 |
| 3 | Media intake at the A2A server | an accepted image is stored and the turn runs | — | tests/integration/media/test_a2a_intake.py:122 |
| 4 | Media intake at the A2A server | a file part by URL is refused, never fetched | — | tests/integration/media/test_a2a_intake.py:148 |
| 5 | Compaction keeps the media named | compaction names every media item | docs/specs/issue-38/requirements.md#R6.2 | tests/integration/media/test_compaction.py:47 |
| 6 | 0.8.0 tasks keep working | a 0.8.0 workflow history replays on this code | docs/specs/issue-38/requirements.md#R5 | tests/integration/media/test_compat.py:55 |
| 7 | 0.8.0 tasks keep working | a 0.8.0 agent state and state record deserialise | docs/specs/issue-38/requirements.md#R5 | tests/integration/media/test_compat.py:71 |
| 8 | Media survives a worker restart | media survives a worker restart | docs/specs/issue-38/requirements.md#R6.4 | tests/integration/media/test_durability.py:57 |
| 9 | Images from the agent | generate_image shows an image and a later turn sees it | docs/specs/issue-38/requirements.md#R2 | tests/integration/media/test_generate_image.py:67 |
| 10 | Images from the agent | an instance without image generation offers no generate_image tool | docs/specs/issue-38/requirements.md#R5.5 | tests/integration/media/test_generate_image.py:131 |
| 11 | Media in the conversation history | media sent from one surface is fetched by another participant on the task | docs/specs/issue-38/requirements.md#R6 | tests/integration/media/test_history_media.py:49 |
| 12 | The media route streams a growing object | chunks arrive as they are appended, and done ends the stream cleanly | — | tests/integration/media/test_media_route.py:86 |
| 13 | The media route streams a growing object | speech that fails or is retried aborts the stream; replay reads the retry | — | tests/integration/media/test_media_route.py:113 |
| 14 | The media route | a mounted agent serves a task's media to its participants only | — | tests/integration/media/test_media_route.py:146 |
| 15 | Media reaches the model | an image and a question reach the model | docs/specs/issue-38/requirements.md#R1 | tests/integration/media/test_model_media.py:52 |
| 16 | Media reaches the model | a model without image input gets a note and the task continues | docs/specs/issue-38/requirements.md#R1.7 | tests/integration/media/test_model_media.py:90 |
| 17 | A full-size image travels from the client to the store and back | a 20 MiB image is accepted, stored and served; a larger body gets 413 | — | tests/integration/media/test_size.py:47 |
| 18 | Spoken replies, streamed | a voice turn is transcribed, answered and spoken | docs/specs/issue-38/requirements.md#R4.1 | tests/integration/media/test_speech.py:144 |
| 19 | Spoken replies, streamed | the speech artifact arrives before the final status | docs/specs/issue-38/requirements.md#R4.2 | tests/integration/media/test_speech.py:189 |
| 20 | Spoken replies, streamed | a retry during speech starts a new generation and the reader is told | docs/specs/issue-38/requirements.md#R4.2 | tests/integration/media/test_speech.py:225 |
| 21 | Spoken replies, streamed | speech that fails leaves the text and a note | docs/specs/issue-38/requirements.md#R4.5 | tests/integration/media/test_speech.py:265 |
| 22 | Spoken replies, streamed | rollover and completion wait for speech; cancel stops it | docs/specs/issue-38/requirements.md#R4 | tests/integration/media/test_speech.py:300 |
| 23 | Spoken replies, streamed | completion waits for the last spoken reply | docs/specs/issue-38/requirements.md#R4 | tests/integration/media/test_speech.py:342 |
| 24 | Spoken replies, streamed | speech still running when the drain ends is stopped with a note | docs/specs/issue-38/requirements.md#R4.5 | tests/integration/media/test_speech.py:374 |
| 25 | Audio reaches the model | a recording is transcribed and the transcript is shown | docs/specs/issue-38/requirements.md#R3.4 | tests/integration/media/test_transcribe.py:43 |
| 26 | Audio reaches the model | native audio skips speech-to-text | docs/specs/issue-38/requirements.md#R3.4 | tests/integration/media/test_transcribe.py:81 |
| 27 | Audio reaches the model | audio with no speech-to-text configured gets a note | docs/specs/issue-38/requirements.md#R1.6 | tests/integration/media/test_transcribe.py:121 |
| 28 | Audio reaches the model | a failed transcription leaves a note and the turn continues | docs/specs/issue-38/requirements.md#R3.4 | tests/integration/media/test_transcribe.py:157 |
