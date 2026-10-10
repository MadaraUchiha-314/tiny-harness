"""``uv run python -m examples.demo``: the one-instance demo of requirement 24.

Runs the A2A server with a worker in the same process, serves the built web renderer
under ``/ui`` and prints how to reach both surfaces. The e2e tests start the server and
the worker as separate processes instead, so they can kill the worker.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from tiny_harness.config import Settings
from tiny_harness.service import commands

CONFIG = Path(__file__).parent / "config.toml"


def main() -> int:
    settings = Settings.load(CONFIG)
    print(f"tiny-harness demo · A2A 1.0 at {settings.server.base_url}", file=sys.stderr)
    print(f"  web renderer: {settings.server.base_url}ui/", file=sys.stderr)
    print(
        f"  TUI:          uv run tiny-harness tui --url {settings.server.base_url}", file=sys.stderr
    )
    return asyncio.run(commands.serve(settings, with_worker=True))


if __name__ == "__main__":
    raise SystemExit(main())
