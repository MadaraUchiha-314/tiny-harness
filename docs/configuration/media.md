# Images and voice

These settings let the agent receive images and audio, speak its replies and make
images. This page is for CLI users and SDK users.

Without these sections, the agent uses text only. The server refuses every file that a
client sends.

| Section | What it turns on | Without it |
|---------|------------------|------------|
| [`[media]`](#media-settings) | Images and audio files in messages. The limits for each file | Text only. The other three sections stop tiny-harness |
| [`[speech_to_text]`](#speech-to-text-settings) | Audio files and voice messages become text for the model | The agent accepts no audio, except for a model that takes audio itself |
| [`[text_to_speech]`](#text-to-speech-settings) | Spoken replies to a voice message | Text replies only |
| [`[image_generation]`](#image-generation-settings) | The `generate_image` tool: the agent can make images | The agent cannot make images |

These services use OpenAI. They use the `OPENAI_API_KEY` and the `base_url` of the
[`[openai]`](models) section. They need no other secret.

## Example

This file turns on everything:

```toml
[openai]
model = "gpt-6.1-sol"

[media]

[speech_to_text]
model = "gpt-4o-mini-transcribe"

[text_to_speech]
model = "gpt-4o-mini-tts"
voice = "coral"

[image_generation]
model = "gpt-image-2"
```

An empty `[media]` line is enough. It uses the default limits.

The TUI needs two optional packages for voice and inline images. See
[Images and voice in the TUI](../cli/tui#images-and-voice).

## What the agent accepts

| Kind | Types |
|------|-------|
| Images | PNG, JPEG, WebP, GIF |
| Audio | WAV, MP3, M4A (`audio/mp4`), Ogg, WebM |

The server reads the start of each file. A file whose content does not match its type
is refused. So is a file that is too large, an image with too many pixels, and audio
that is too long. The client gets an error that names the limit. The server keeps
nothing of a refused message.

The model sees each image. Each audio file goes through speech-to-text, and the model
reads the text. If the model takes no images, the agent tells you that it did not see
the image, and the task continues.

## `[media]` settings {#media-settings}

| Setting | Default |
|---------|---------|
| [`max_file_bytes`](#max-file-bytes) | `20971520` (20 MiB) |
| [`max_message_bytes`](#max-message-bytes) | `26214400` (25 MiB) |
| [`max_image_pixels`](#max-image-pixels) | `40000000` |
| [`max_audio_seconds`](#max-audio-seconds) | `120` |
| [`max_request_media_bytes`](#max-request-media-bytes) | `20971520` (20 MiB) |
| [`dir`](#dir) | `media/` beside the store file |
| [`speech_drain`](#speech-drain) | `"PT120S"` (120 seconds) |

### `max_file_bytes` {#max-file-bytes}

The largest file in a message, in bytes.

- **Default:** `20971520` (20 MiB)
- It must not be larger than `max_message_bytes`. If it is, tiny-harness does not start.

### `max_message_bytes` {#max-message-bytes}

The largest total size of all the files in one message, in bytes.

- **Default:** `26214400` (25 MiB)
- The server accepts requests large enough for this total. It uses the larger of
  [`max_request_bytes`](server#max-request-bytes) and this value plus the encoding
  overhead (about one third more).

### `max_image_pixels` {#max-image-pixels}

The largest image, as width × height in pixels. The server reads the size from the
file header. It does not decode the image. For a GIF, the size is the area that covers
the screen and every frame. A frame that is larger than the screen counts.

- **Default:** `40000000` (for example, 8000 × 5000)

### `max_audio_seconds` {#max-audio-seconds}

The longest audio file or voice message, in seconds.

- **Default:** `120`

### `max_request_media_bytes` {#max-request-media-bytes}

The largest total size of the files in one request to the model, in bytes.

- **Default:** `20971520` (20 MiB)
- Each turn sends the images of the conversation again. The newest files go first.
  When the total is too large, the model gets the text
  `[image <name> shown earlier, not re-sent]` in place of an older image.
- A number greater than zero.
- Some models also have a limit for each image. Anthropic models take an image of up
  to 5 MiB as base64. For a larger image, the model gets the text
  `[image <name> too large for this model]`.

### `dir`

The folder where tiny-harness keeps the files of each task.

- **Default:** `media/` in the folder of the [store file](storage#sqlite-path). An agent
  with an [`[agent] id`](agent) other than `tiny-harness` uses `media-<id>/`.
- **Set it when:** you want the files on another disk.
- The server and all workers must use the same folder.
- The folder holds personal data: photos and recordings of voices. Keep it private.
  [`[retention] media`](storage#retention-settings) sets how long tiny-harness keeps it.

### `speech_drain` {#speech-drain}

How long tiny-harness waits for a spoken reply to finish before it completes a task.

- **Default:** `"PT120S"` (120 seconds)
- After this time, tiny-harness stops the reply and tells the user that speech is not
  available. The text reply is not changed.
- A duration greater than zero.

## `[speech_to_text]` settings {#speech-to-text-settings}

Speech-to-text turns an audio file or a voice message into text.

| Setting | Default | What it does |
|---------|---------|--------------|
| `provider` | `"openai"` | The service. `"openai"` is the only value |
| `model` | `"gpt-4o-mini-transcribe"` | The speech-to-text model |

```toml
[speech_to_text]
model = "gpt-4o-mini-transcribe"
```

The user sees the text under their voice message.

## `[text_to_speech]` settings {#text-to-speech-settings}

Text-to-speech speaks the agent's reply. tiny-harness speaks a reply when the user's
message asks for it. The TUI and the web renderer ask for it when spoken replies are
on.

| Setting | Default | What it does |
|---------|---------|--------------|
| `provider` | `"openai"` | The service. `"openai"` is the only value |
| `model` | `"gpt-4o-mini-tts"` | The text-to-speech model |
| `voice` | `"coral"` | The voice. Use a voice name that the model knows |
| `instructions` | `""` | How to speak, for example `"Speak slowly and calmly."` |

```toml
[text_to_speech]
model = "gpt-4o-mini-tts"
voice = "coral"
instructions = "Speak in a warm, friendly tone."
```

The reply starts to play before the audio is complete. tiny-harness speaks the text
without Markdown, and speaks at most the first 4 096 characters. If text-to-speech
fails, the text reply stays and the user sees "speech unavailable".

## `[image_generation]` settings {#image-generation-settings}

This section gives the agent the `generate_image` tool. The agent calls it to make an
image. The user sees the image in the conversation.

| Setting | Default | What it does |
|---------|---------|--------------|
| `provider` | `"openai"` | The service. `"openai"` is the only value |
| `model` | `"gpt-image-2"` | The image model |
| `size` | `"1024x1024"` | The default size: `"1024x1024"`, `"1536x1024"` or `"1024x1536"` |

```toml
[image_generation]
model = "gpt-image-2"
size = "1536x1024"
```

A later message can refer to a generated image, as to an image that the user sent.

## Models that take images or audio

The [`[openai]`](models) section has two more settings for media.

### `input_modalities` {#input-modalities}

What the model takes as input: `"text"`, `"image"` and `"audio"`.

- **Default:** `["text", "image"]` with `api = "responses"`. `["text"]` with
  `api = "chat_completions"`, so a local model does not get images that it cannot
  read.
- **Set it when:** your model reads images on Chat Completions, or takes audio itself.
- The list must contain `"text"`.
- Add `"audio"` only for a Chat Completions model that takes audio. That model then
  gets WAV and MP3 files without speech-to-text.

```toml
[openai]
base_url = "http://127.0.0.1:11434/v1"
api = "chat_completions"
model = "qwen2.5vl:7b"
input_modalities = ["text", "image"]
```

### `audio_tokens_per_second` {#audio-tokens-per-second}

The number of tokens that one second of audio costs, for a model that takes audio
itself. tiny-harness uses it to estimate the size of the model's input.

- **Default:** `10`
- A whole number greater than 0.

## When a setting is wrong

tiny-harness does not start, and names the setting:

- `[speech_to_text]`, `[text_to_speech]` or `[image_generation]` without `[media]`.
- `max_file_bytes` larger than `max_message_bytes`.
- A `provider` other than `"openai"`, or a `size` that is not in the list.
