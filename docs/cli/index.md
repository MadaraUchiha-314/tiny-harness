# CLI quickstart

This guide is for people who want to chat with an agent in the terminal. You do not
write code. If you want to run the agent inside your own Python application, read the
[SDK quickstart](../sdk/) instead.

## What you need

- Python 3.14 or later.
- An OpenAI API key. No key? Use a local model. See [Use a local model](#use-a-local-model).

## Start in three steps

1. Install tiny-harness:

   ```sh
   pip install tiny_harness
   ```

2. Give tiny-harness your OpenAI key:

   ```sh
   export OPENAI_API_KEY=sk-...
   ```

3. Start the TUI (the terminal user interface):

   ```sh
   tiny-harness
   ```

You see the conversation on the left, the task details on the right and a message box
at the bottom. Type a message and press Enter. The agent replies in the conversation.

## What happens on the first run

- tiny-harness creates the folder `~/.tiny-harness/` and the configuration file
  `~/.tiny-harness/config.toml` in it. It prints the path of the file.
- tiny-harness downloads the Temporal server one time, into
  `~/.cache/tiny-harness/temporal`. Temporal keeps your tasks safe when the program
  stops. You do not need a Temporal account.
- Your conversations, and the log file `tiny-harness.log`, stay in `~/.tiny-harness/`.

tiny-harness never changes the configuration file after it creates it. Edit it when you
want. The [configuration guide](../configuration/) explains each setting.

## Use a local model

You can use a model that runs on your own computer with [Ollama](https://ollama.com).
You do not need an API key.

1. Start Ollama and download a model that can call tools:

   ```sh
   OLLAMA_CONTEXT_LENGTH=16384 ollama serve &
   ollama pull qwen3:8b
   ```

2. Open `~/.tiny-harness/config.toml` and replace the `[openai]` section with this:

   ```toml
   [openai]
   base_url = "http://127.0.0.1:11434/v1"
   api = "chat_completions"
   model = "qwen3:8b"
   context_window_tokens = 16384
   ```

3. Start tiny-harness without a key:

   ```sh
   unset OPENAI_API_KEY
   tiny-harness
   ```

The value of `context_window_tokens` must be the same as `OLLAMA_CONTEXT_LENGTH`. Other
servers, such as OpenRouter, vLLM and LM Studio, work the same way. See
[Models](../configuration/models).

## Next steps

- [Use the TUI](tui): keys, commands, and how a conversation ends.
- [Images and voice](tui#images-and-voice): show the agent a photo, and talk to it.
- [Configuration](../configuration/): change the model, the folders and more.
- [Connect to a shared server](tui#connect-to-a-server): chat with an agent that runs
  on another computer.
