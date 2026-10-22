"""``uv run python -m examples.multimodal [CONFIG]``: the multi-modal demo (issue-38 R7).

Runs the A2A server with an embedded Temporal and the worker in the same process, serves
the built web renderer under ``/ui`` and prints how to start the TUI. ``CONFIG`` defaults
to ``config.toml`` beside this file: OpenAI for the model, speech-to-text, text-to-speech
and images, and the plugin that makes the agent an interior design helper. It calls
``tiny_harness.service.serve``, the same entry point a consumer's program uses.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from tiny_harness.config import Settings
from tiny_harness.service import serve

CONFIG = Path(__file__).parent / "config.toml"
FIXTURES = Path(__file__).parent / "fixtures"


def banner(settings: Settings) -> str:
    """What to open: the web renderer, the TUI command and the fixtures to try."""
    base = settings.server.base_url
    return "\n".join(
        [
            f"tiny-harness multi-modal demo · A2A 1.0 at {base}",
            f"  Temporal:     {settings.temporal.mode}",
            f"  web renderer: {base}ui/",
            f"  TUI:          uv run tiny-harness tui --url {base}",
            "                voice and inline images need the extras: uv sync --extra voice",
            '                --extra images, or pip install "tiny-harness[voice,images]"',
            f"  try:          /attach {FIXTURES / 'room.jpg'}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    config = Path(args[0]) if args else CONFIG
    settings = Settings.load(config)
    print(banner(settings), file=sys.stderr)
    return asyncio.run(serve(settings, with_worker=True))


if __name__ == "__main__":
    raise SystemExit(main())
