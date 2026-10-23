# T4 — end-to-end demo against OpenAI (and T7 latency)

Work item issue-38, activities T4 and T7. `tests/e2e/test_demo_multimodal.py` runs
`examples/multimodal` on embedded Temporal with real OpenAI calls, driven through the A2A
client with the committed fixtures (`room.jpg`, `question.wav`, `followup.wav`).

2026-10-22 (run started 20:03:38Z), branch `issue-38-multimodal` at `8d924e3`
(the server code is the same at `ec5f6b8`; that commit adds a test only), Python 3.14.7.
`OPENAI_API_KEY` came from the environment and is not written here.

| Role | Model |
|------|-------|
| LLM | `gpt-6.1-sol` (Responses API) |
| Speech-to-text | `gpt-4o-mini-transcribe` |
| Text-to-speech | `gpt-4o-mini-tts`, voice `coral` |
| Image generation | `gpt-image-2`, 1024x1024 |

## Command

```text
env -u TEMPORAL_API_KEY TINY_HARNESS_E2E_EVIDENCE=~/.cache/th38v/e2e \
  uv run pytest tests/e2e/test_demo_multimodal.py -s -q
```

`TEMPORAL_API_KEY` is unset so that the demo uses its embedded Temporal server, as the
plan's environment says. `TINY_HARNESS_E2E_EVIDENCE` makes the test write the generated
image and the reply excerpt.

## Latency (T7)

Time from the voice turn's final status (`TASK_STATE_INPUT_REQUIRED`) to the first PCM
chunk at the client, read through the media route:

**0.311 s** (target ≤ 1.5 s; reported, not a CI gate because it depends on OpenAI).

The spoken reply was 420 000 bytes: 8.75 s of 24 kHz mono 16-bit PCM, an even length
(well-formed samples). An earlier run on the same server code (19:38Z, before the
TUI and web stop-on-send fixes) measured 1.056 s; both are under the target.

## Run output

The transcript of A2A events (timestamps from the start of the test), then the summary
the test prints:

```text
[   6.2s] task           TASK_STATE_SUBMITTED     32905f12-4167-4a17-8f11-3fdd19a677be
[   6.6s] artifact_update                          user message
[   6.6s] status_update  TASK_STATE_WORKING       
[  13.6s] status_update  TASK_STATE_INPUT_REQUIRED Your living room has a charcoal-grey sofa, a wooden coffee table and a pale patterned rug against warm beige walls. Daylight filters through sheer white curtains beside a slim black floor lamp, giving the room a calm, cosy feel.
[  13.9s] artifact_update                          user message
[  14.7s] artifact_update                          transcript
[  14.7s] status_update  TASK_STATE_WORKING       
[  17.8s] status_update  TASK_STATE_INPUT_REQUIRED I’d paint the walls a warm off-white with a soft cream undertone to brighten the room without making it feel cold. It would work well with your charcoal sofa, wooden coffee table and sheer white curtains.
[  18.2s] artifact_update                          user message
[  19.0s] artifact_update                          transcript
[  19.0s] status_update  TASK_STATE_WORKING       
[  38.1s] artifact_update                          Mockup of your living room with warm off-white walls, keeping the grey sofa, wooden coffee table and sheer curtains.
[  42.0s] artifact_update                          speech
[  42.2s] status_update  TASK_STATE_INPUT_REQUIRED Here’s your room with warm off-white walls, giving it a brighter feel while keeping the grey sofa, wooden coffee table and sheer curtains.
[  43.9s] status_update  TASK_STATE_WORKING       
[  67.7s] artifact_update                          The original living room with a forest-green sofa, keeping the beige walls, wooden coffee table and sheer curtains.
[  71.9s] status_update  TASK_STATE_INPUT_REQUIRED Here’s a mockup of your first photo with a deep green sofa, keeping the original beige walls and wooden coffee table.
{
  "latency_first_chunk_after_final_status_s": 0.3105459980433807,
  "latency_target_s": 1.5,
  "speech_bytes": 420000,
  "speech_seconds": 8.75,
  "generated_images": 2,
  "generate_image_calls": 2,
  "states": [
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_INPUT_REQUIRED"
  ]
}
.
1 passed in 75.77s (0:01:15)
exit=0
```

The four turns: (1) the photo with a question — the model describes the room; (2) the
audio file `question.wav` — transcribed, then answered; (3) a voice turn
(`followup.wav`, sent as a voice note) — transcribed, the agent calls `generate_image`,
the image artifact arrives, the spoken reply's `speech` artifact arrives before the final
status, and the reply streams through the media route; (4) the back-reference turn —
"the first photo" — the agent generates a second image from the original photo. The task
then completes.

The test also asserts: the photo is stored and echoed by reference with identical bytes;
both transcripts are non-empty and the voice transcript names the request; each generated
image starts with the PNG signature; only the voice turn was spoken; and neither the
trace nor `server.log` holds the value of any secret variable, the base64 or the `repr` of
any fixture, generated image or the first 3 KiB of speech.

## Files

| File | What it is |
|------|------------|
| [`e2e/generated.png`](e2e/generated.png) | The first image `gpt-image-2` generated (turn 3), 1024 × 1024 PNG, as fetched through the media route |
| [`e2e/reply-excerpt.wav`](e2e/reply-excerpt.wav) | The first 5.00 s of the spoken reply to turn 3 (synthetic voice `coral`), wrapped as WAV, 24 kHz mono 16-bit |

No committed audio carries a person's voice: the fixtures and the reply are synthetic.
