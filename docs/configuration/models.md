# Models

These settings choose the AI model that the agent uses. tiny-harness works with:

- **OpenAI**, through the `[openai]` section.
- **Any server that copies the OpenAI API**: Ollama, OpenRouter, vLLM, LM Studio and
  others. Use the `[openai]` section with `base_url`.
The agent always uses the `[openai]` section. tiny-harness also has an Anthropic
adapter, but the CLI and `running_harness` do not use it yet. See
[`[anthropic]`](#anthropic-settings).

## Examples

OpenAI:

```toml
[openai]
model = "gpt-6.1-sol"
reasoning_effort = "medium"
```

```sh
export OPENAI_API_KEY=sk-...
```

A local Ollama, with no key:

```toml
[openai]
base_url = "http://127.0.0.1:11434/v1"
api = "chat_completions"
model = "qwen3:8b"
context_window_tokens = 16384
timeout = "PT600S"
```

OpenRouter:

```toml
[openai]
base_url = "https://openrouter.ai/api/v1"
api = "chat_completions"
model = "provider/model-name"      # a model name from openrouter.ai/models
```

```sh
export OPENAI_API_KEY=sk-or-...   # your OpenRouter key
```

## `[openai]` settings

| Setting | Default |
|---------|---------|
| [`model`](#model) | `"gpt-6.1-sol"` |
| [`models`](#models) | `model` only |
| [`reasoning_effort`](#reasoning-effort) | none |
| [`base_url`](#base-url) | `"https://api.openai.com/v1"` |
| [`api`](#api) | `"responses"` |
| [`context_window_tokens`](#context-window-tokens) | known for OpenAI models, else 400 000 |
| [`max_output_tokens`](#max-output-tokens) | `2000` |
| [`timeout`](#timeout) | `"PT60S"` (60 seconds) |
| [`input_modalities`](media#input-modalities) | `["text", "image"]`, or `["text"]` with `chat_completions` |
| [`audio_tokens_per_second`](media#audio-tokens-per-second) | `10` |

### `model`

The model the agent uses for a new task.

- **Default:** `"gpt-6.1-sol"`
- Use a name that your server knows. For Ollama, that is the name you pulled, for
  example `"qwen3:8b"`.

### `models`

The models that a user can choose with the `/model` command.

- **Default:** only `model`.
- **Set it when:** you want users to switch models in a task.
- **Example:** `models = ["gpt-6.1-sol", "my-other-model"]`
- The list must contain `model`. An empty list, or a list without `model`, stops
  tiny-harness.

### `reasoning_effort` {#reasoning-effort}

How much the model thinks before it answers: `"low"`, `"medium"` or `"high"`. A user
can change it in a task with `/effort`.

- **Default:** none. tiny-harness sends no effort, and the model uses its own default.
- A model that does not accept an effort can refuse the request. Leave it unset for
  such a model.

### `base_url` {#base-url}

The address of an OpenAI-compatible server.

- **Default:** `"https://api.openai.com/v1"`
- **Set it when:** you use a server other than OpenAI. With `base_url`,
  `OPENAI_API_KEY` is optional.
- tiny-harness sends requests to this address only. It ignores the `OPENAI_BASE_URL`
  environment variable.
- These values stop tiny-harness:
  - An address with a user name or password in it (`https://user:pass@...`). Put the
    key in `OPENAI_API_KEY`.
  - An `http://` address to another computer while `OPENAI_API_KEY` is set. Use
    `https://`, so the key is not sent in clear text. `http://` is allowed for
    `localhost` and `127.0.0.1`.

### `api`

Which OpenAI API the server speaks.

- **Default:** `"responses"` (the OpenAI Responses API)
- **Set it when:** your server has only the older Chat Completions API. Then use
  `"chat_completions"`. Many local servers need this.
- For OpenAI's own reasoning models, keep `"responses"`.

### `context_window_tokens` {#context-window-tokens}

The maximum input size of the model, in tokens. When a conversation becomes too long,
tiny-harness writes a summary of the older part. It uses this number to decide when.

- **Default:** tiny-harness knows the size of OpenAI models. For other models it uses
  400 000.
- **Set it when:** you use a model that tiny-harness does not know, or a server that
  gives the model a smaller window. For Ollama, use the value of
  `OLLAMA_CONTEXT_LENGTH`.
- A whole number greater than 0.

### `max_output_tokens` {#max-output-tokens}

The maximum length of one model reply, in tokens.

- **Default:** `2000`

### `timeout`

How long tiny-harness waits for one model reply.

- **Default:** `"PT60S"` (60 seconds)
- **Set it when:** your model is slow. A local model can need `"PT600S"`.

When a model call fails because of a timeout, a rate limit or a server error,
tiny-harness tries again. See [`[retries]`](tuning#retries).

### Images and audio

`input_modalities` and `audio_tokens_per_second` tell tiny-harness what the model
reads. [Images and voice](media#models-that-take-images-or-audio) explains them.

## `[anthropic]` settings

tiny-harness reads and checks this section. The CLI and `running_harness` do not use
it yet, so the agent uses `[openai]`. The Anthropic adapter is not tested end to end.

```toml
[anthropic]
model = "claude-opus-5-5"
```

```sh
export ANTHROPIC_API_KEY=...
```

| Setting | Default | What it does |
|---------|---------|--------------|
| `model` | `"claude-opus-5-5"` when only the key is set | The model |
| `models` | `model` only | The models `/model` can choose. Same rules as [`[openai] models`](#models) |
| `reasoning_effort` | none | Same as [`[openai] reasoning_effort`](#reasoning-effort) |
