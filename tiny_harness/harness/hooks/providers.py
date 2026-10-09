"""Infrastructure providers (R2.7): the async HTTP client, the clock and the random source.

These are not serialisable hooks but objects given to the harness at construction;
activities read them from the worker's dependency container, while workflow code uses
Temporal's own ``workflow.now()`` and ``workflow.random()``. The defaults are the real
thing; tests pass fakes.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

Clock = Callable[[], datetime]
"""Returns the current time, timezone-aware."""

RandomSource = Callable[[], float]
"""Returns a float in [0, 1); the only randomness the harness draws outside Temporal."""

HttpClientFactory = Callable[[], httpx.AsyncClient]
"""Builds the async HTTP client remote hooks, model adapters and A2A clients use."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def default_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(30.0))


@dataclass(frozen=True)
class Providers:
    """The three infrastructure dependencies the harness does not own."""

    http_client_factory: HttpClientFactory = default_http_client
    clock: Clock = utc_now
    random: RandomSource = field(default=random.random)


__all__ = [
    "Clock",
    "HttpClientFactory",
    "Providers",
    "RandomSource",
    "default_http_client",
    "utc_now",
]
