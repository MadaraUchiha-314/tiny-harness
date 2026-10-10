"""Transport limits in front of every route (abuse case 7): request size and a per-peer
token bucket, so an oversized or flooding request is rejected before anything reaches
Temporal or the store."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Final, cast

Scope = MutableMapping[str, object]
Message = MutableMapping[str, object]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

TOO_LARGE: Final = 413
TOO_MANY: Final = 429


class TokenBucket:
    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}

    def take(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        tokens, last = self._buckets.get(key, (self.capacity, now))
        tokens = min(self.capacity, tokens + (now - last) * self.rate)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True


class LimitsMiddleware:
    def __init__(self, app: ASGIApp, *, max_request_bytes: int, rate_limit_per_minute: int) -> None:
        self.app = app
        self.max_bytes = max_request_bytes
        self.bucket = TokenBucket(rate_limit_per_minute)
        self.rejected: list[tuple[str, int]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        peer = str(client[0]) if isinstance(client, (tuple, list)) and client else "unknown"  # type: ignore[index]
        if not self.bucket.take(peer):
            self.rejected.append((peer, TOO_MANY))
            await _reject(send, TOO_MANY, "rate limit exceeded")
            return
        declared = _content_length(scope.get("headers"))
        if declared > self.max_bytes:
            self.rejected.append((peer, TOO_LARGE))
            await _reject(send, TOO_LARGE, "request too large")
            return
        seen = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body")
                seen += len(body) if isinstance(body, bytes) else 0
                if seen > self.max_bytes:
                    self.rejected.append((peer, TOO_LARGE))
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await _reject(send, TOO_LARGE, "request too large")


class _TooLarge(Exception):
    pass


def _content_length(headers: object) -> int:
    if not isinstance(headers, list):
        return 0
    for item in cast(list[tuple[bytes, bytes]], headers):
        if item[0].lower() == b"content-length":
            try:
                return int(item[1] or b"0")
            except ValueError:
                return 0
    return 0


async def _reject(send: Send, status: int, text: str) -> None:
    body = text.encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


__all__ = ["TOO_LARGE", "TOO_MANY", "LimitsMiddleware", "TokenBucket"]
