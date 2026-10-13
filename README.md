# tiny-harness

tiny-harness runs an AI agent that can hold a conversation, call tools and survive a
crash. You can use it in two ways:

- **In your terminal.** Install one command and chat with the agent in a terminal user
  interface (the TUI).
- **In your Python application.** Start the agent from your own code and serve it to
  your users over the [A2A protocol](https://a2a-protocol.org/).

Full documentation: [madarauchiha-314.github.io/tiny-harness](https://madarauchiha-314.github.io/tiny-harness/)

## Quickstart: chat in your terminal

You need Python 3.14 and an OpenAI API key.

```sh
pip install tiny_harness
export OPENAI_API_KEY=sk-...
tiny-harness
```

The TUI opens. Type a message and press Enter.

On the first run, tiny-harness creates its configuration file at
`~/.tiny-harness/config.toml`. It also downloads the Temporal server one time. Temporal
keeps your tasks safe when the program stops.

No OpenAI key? Use a local model with [Ollama](https://ollama.com). See
[Models](https://madarauchiha-314.github.io/tiny-harness/configuration/models).

Read more: [CLI guide](https://madarauchiha-314.github.io/tiny-harness/cli/).

## Quickstart: run it in your Python application

```sh
pip install tiny_harness
export OPENAI_API_KEY=sk-...
```

Write a configuration file, `config.toml`:

```toml
[temporal]
mode = "embedded"                  # tiny-harness starts Temporal for you

[openai]
model = "gpt-6.1-sol"

[server]
base_url = "http://127.0.0.1:8080"
```

Start the agent from your code:

```python
import asyncio
from pathlib import Path

from tiny_harness.config import Settings
from tiny_harness.service import running_harness


async def main() -> None:
    settings = Settings.load(Path("config.toml"))  # secrets come from the environment
    async with running_harness(settings) as harness:
        print(f"Agent ready at {harness.base_url}")
        await harness.wait()  # serve until the process stops


asyncio.run(main())
```

Any A2A client can now talk to the agent at `harness.base_url`.

Read more: [SDK guide](https://madarauchiha-314.github.io/tiny-harness/sdk/).

## Documentation

| I want to … | Read |
|-------------|------|
| Chat with an agent in my terminal | [CLI guide](https://madarauchiha-314.github.io/tiny-harness/cli/) |
| Run the agent in my Python application | [SDK guide](https://madarauchiha-314.github.io/tiny-harness/sdk/) |
| Add one or more agents to my Starlette or FastAPI app | [Mount agents on your app](https://madarauchiha-314.github.io/tiny-harness/sdk/mount) |
| Change a setting | [Configuration](https://madarauchiha-314.github.io/tiny-harness/configuration/) |
| Put the agent in production | [Deploy](https://madarauchiha-314.github.io/tiny-harness/sdk/deploy) |
| Work on tiny-harness itself | [Developer guide](https://madarauchiha-314.github.io/tiny-harness/develop/) |

## License

Apache-2.0. See [LICENSE](LICENSE).
