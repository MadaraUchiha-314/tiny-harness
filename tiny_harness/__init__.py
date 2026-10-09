"""tiny-harness: an opinionated, production-grade agent harness.

The package mirrors the architecture diagram of issue #3: ``interaction`` (surfaces and
renderers), ``service`` (the app service layer: A2A server, inbox, heartbeat, channels,
observability, durable execution), ``harness`` (the pluggable entities and the core loop)
and ``builtin`` (the default plugin). ``config`` and ``errors`` are shared by all three.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tiny_harness")
except PackageNotFoundError:  # pragma: no cover - only when run from an unbuilt checkout
    __version__ = "0.0.0"

__all__ = ["__version__"]
