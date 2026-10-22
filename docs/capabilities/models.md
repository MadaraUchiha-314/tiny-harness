# Capability: models

> One LLM interface over the providers' official SDKs (OpenAI Responses API first, Chat
> Completions for OpenAI-compatible servers, Anthropic Messages API beside it) and a
> System One interface designed against Jev.

## What it is

Provider choice as configuration. The LLM entity has invoke and streaming operations,
tool-call extraction and structured output; durable execution owns retrying, so the
clients' own retries are off. Lives in `tiny_harness/harness/models/`.

## Current behaviour

- An `LLMRequest` SHALL carry the static prefix (`instructions`), the per-turn input
  items, the tool definitions and an optional structured-output schema; an `LLMResponse`
  the text, the tool calls, the usage (input, output and cached tokens), the model and
  the finish reason (`stop`, `tool_calls`, `length`, `refusal`).
- An `LLMRequest` SHALL also carry an optional `model` and `reasoning_effort` (`low`,
  `medium`, `high`); each adapter uses `request.model` or its configured model. Every
  model request of a task (the turn, the compaction summary, help routing) SHALL take
  them from `ModelCatalog.settings_for` (the task's `/model` and `/effort` choice, else
  the configured default). The effort SHALL be sent only when set, so an unset effort
  keeps requests byte-identical: `reasoning={"effort": v}` on the Responses API,
  `reasoning_effort=v` on Chat Completions, `output_config={"effort": v}` on Anthropic.
- `ModelCatalog` (`models/catalog.py`) SHALL hold the default model, the selectable
  models (`models`, else the default alone), the default effort and each model's context
  window; compaction looks the window up for the task's current model when it decides.
  The chat span's `gen_ai.request.model` is the per-request model and
  `tiny_harness.llm.reasoning_effort` is set when an effort is.
- The OpenAI adapter SHALL use the Responses API with `instructions` as the cached prefix,
  `prompt_cache_key` = the task id, `store=false`, `max_retries=0`; the default model is
  `gpt-6.1-sol` (the only e2e model). A 429, 5xx, timeout or connection failure SHALL be
  raised as `RetryableProviderError`, any other provider error as `ProviderError`.
- The OpenAI adapter SHALL send every request to `[openai] base_url` (default
  `https://api.openai.com/v1`) and to no other host: the client is always built with an
  explicit URL, so `OPENAI_BASE_URL` is never read (the runtime logs one WARNING, without
  its value, when it is set), and a custom endpoint's redirects are refused. A custom endpoint SHALL receive no `OpenAI-Organization` / `OpenAI-Project`
  headers, and with no key no `Authorization` header.
- WHERE `api = "chat_completions"` the adapter SHALL call `/chat/completions`: the prefix
  as the leading `system` message, the calls of a turn grouped in one `assistant`
  message, tool results as `tool` messages, `max_tokens`, `json_schema` structured
  output, no `store` or `prompt_cache_key`; streamed tool-call fragments are assembled
  and emitted when the stream ends; absent usage or call ids read as zero / `call_<n>`.
  The finish reason is `refusal` (a refusal or `content_filter`), else `tool_calls` when
  any call is present, else `length`, else `stop`.
- A 2xx body either wire API cannot parse SHALL be raised as `ProviderError(status=200)`,
  including JSON nested too deeply to decode and a Chat Completions stream that ends
  without a `finish_reason`, which emits no tool call and no `done`.
- `LLMModelInfo` SHALL carry `context_window_tokens` (`[openai] context_window_tokens`,
  else the table, else 400 000), `endpoint` (`scheme://host[:port]`) and `api`; the
  runtime logs `model endpoint <endpoint> api=<api> model=<model>` at startup, and the
  chat span carries `server.address`, `server.port` and `tiny_harness.llm.api`.
- The Anthropic adapter SHALL use the Messages API with the system block marked
  `cache_control: ephemeral`, the same retry contract, and is configurable but not
  exercised end to end.
- Tool names SHALL be encoded per request into provider-safe names and decoded on the
  calls that come back.
- The System One entity SHALL answer typed questions about a state (`noul` with a
  probability, `choice` with the option, its confidence and every option's probability,
  `score` with a rubric level) with a timeout; a deterministic fake ships and the core
  loop does not call it in this work item.
- Provider credentials SHALL come only from `OPENAI_API_KEY` (optional with a
  `base_url`) and `ANTHROPIC_API_KEY`.
- `FakeLLM` SHALL be the scripted implementation tests use.
- `MessageItem.media` SHALL carry the turn's `MediaAttachment`s as references. Inside the
  `invoke_llm` activity an attachment is resolved, and each adapter maps a resolved one:
  an image as `input_image` with a data URL and `detail="auto"` (Responses), an
  `image_url` part (Chat Completions) or a base64 `image` block (Anthropic); native audio
  as `input_audio` with `wav` or `mp3` (Chat Completions only); a transcribed audio file
  as the text `[transcript of <name>] …`. A message with no media SHALL keep its
  plain-string content, so a text-only request is byte-identical to 0.8.0. An attachment
  that reaches an adapter unresolved SHALL raise `ProviderError("media not resolved")`.
- `LLMModelInfo` SHALL state `input_modalities` and `output_modalities` (`text`, `image`,
  `audio`) and `audio_input_formats`. `input_modalities` comes from `[openai]
  input_modalities` (default `["text", "image"]` with Responses, `["text"]` with Chat
  Completions); `audio_input_formats` is the adapter's own (`audio/wav`, `audio/mpeg` for
  Chat Completions, none otherwise). `max_image_bytes` is the adapter's per-image limit
  as base64 (Anthropic 5 242 880, OpenAI none). The harness decides image delivery,
  native audio and transcription from these fields, never from the provider's name.
- The SDK SHALL define `SpeechToText` (`transcribe(audio, *, media_type, name, language)
  -> Transcript`), `TextToSpeech` (`stream(text, *, voice, instructions)` yielding chunks
  in its `AudioFormat`) and `ImageGenerator` (`generate(prompt, *, size) ->
  GeneratedImage`) as entities with a `SpeechModelInfo` / `ImageModelInfo` (provider,
  model, endpoint), each with a scripted fake (`FakeSpeechToText`, `FakeTextToSpeech`,
  `FakeImageGenerator`).
- `OpenAISpeechToText` (`audio.transcriptions`), `OpenAITextToSpeech` (`audio.speech`
  streamed as 16-bit mono PCM at 24 kHz) and `OpenAIImageGenerator` (`images.generate`,
  PNG from `b64_json`) SHALL use the LLM's client factory — `max_retries=0`, the
  configured `base_url` as the only host, redirects refused — and the same error mapping
  (429, 5xx, timeouts → `RetryableProviderError`; others → `ProviderError`). They are
  built from `[speech_to_text]`, `[text_to_speech]` and `[image_generation]`; each
  section absent means that entity is absent.

## Design

[design.md § Models](../specs/issue-3/design.md#models-r18--harnessmodels).
[issue-38 design.md § LLM types](../specs/issue-38/design.md#components-interfaces), [§ Speech and image interfaces](../specs/issue-38/design.md#components-interfaces).

## History

| Work item | What changed | Links |
|-----------|--------------|-------|
| issue-3 | LLM and System One entities, OpenAI and Anthropic adapters, the fake (Layer 3); provider-safe wire names (Layer 9) | [spec](../specs/issue-3/), [PR #9](https://github.com/MadaraUchiha-314/tiny-harness/pull/9) |
| issue-19 | `base_url`, the Chat Completions wire API, the keyless client, `context_window_tokens`, parse failures as `ProviderError`, endpoint observability | [spec](../specs/issue-19/), [PR #22](https://github.com/MadaraUchiha-314/tiny-harness/pull/22), [decision-006](../decisions/decision-006.md) |
| issue-25 | Per-request `model` and `reasoning_effort` on `LLMRequest`, the provider effort mappings, `ModelCatalog` and the per-model context window, for `/model` and `/effort` | [spec](../specs/issue-25/), [PR #26](https://github.com/MadaraUchiha-314/tiny-harness/pull/26), [decision-007](../decisions/decision-007.md) |
| issue-38 | Media content parts in `LLMRequest` and each adapter's mapping; `input_modalities`, `output_modalities`, `audio_input_formats`; the `SpeechToText`, `TextToSpeech` and `ImageGenerator` entities, their OpenAI implementations and fakes | [spec](../specs/issue-38/), [PR #39](https://github.com/MadaraUchiha-314/tiny-harness/pull/39), [decision-010](../decisions/decision-010.md) |
