"""``uv run python -m examples.demo [CONFIG]``: the one-instance demo of requirement 24.

Runs the A2A server with a worker in the same process, serves the built web renderer
under ``/ui`` and prints how to reach both surfaces. ``CONFIG`` defaults to
``config.toml`` (Temporal Cloud); ``examples/demo/config.embedded.toml`` runs it with an
embedded Temporal and no Temporal account (issue-17). It calls ``tiny_harness.service.serve``,
the same entry point a consumer's program uses. The e2e tests start the server and the
worker as separate processes instead, so they can kill the worker.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from tiny_harness.config import Settings
from tiny_harness.service import serve

CONFIG = Path(__file__).parent / "config.toml"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    config = Path(args[0]) if args else CONFIG
    settings = Settings.load(config)
    print(f"tiny-harness demo · A2A 1.0 at {settings.server.base_url}", file=sys.stderr)
    print(f"  Temporal:     {settings.temporal.mode}", file=sys.stderr)
    print(f"  web renderer: {settings.server.base_url}ui/", file=sys.stderr)
    print(
        f"  TUI:          uv run tiny-harness tui --url {settings.server.base_url}", file=sys.stderr
    )
    return asyncio.run(serve(settings, with_worker=True))


if __name__ == "__main__":
    raise SystemExit(main())
