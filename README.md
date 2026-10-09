# tiny-harness

A tiny agent harness.

```python
from tiny_harness import hello_world

hello_world()  # "Hello, world!"
```

## Install

```sh
pip install tiny_harness
```

## Develop

```sh
uv sync                    # creates .venv/ with every dev tool
uv run pre-commit install  # lint, type-check, unit tests + commit-message hooks
```

See [local development](https://madarauchiha-314.github.io/tiny-harness/guide/local-development)
for the full guide, and the [documentation site](https://madarauchiha-314.github.io/tiny-harness/)
for the tech stack, architecture and decisions.
