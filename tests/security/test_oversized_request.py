"""Abuse case 7: an oversized or flooding request is rejected before persistence."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from tiny_harness.service.a2a.middleware import TOO_LARGE, TOO_MANY, LimitsMiddleware

Message = MutableMapping[str, object]


def app_with_limits(seen: list[bytes], *, max_bytes: int = 64, per_minute: int = 2) -> Starlette:
    async def intake(request: Request) -> PlainTextResponse:
        seen.append(await request.body())
        return PlainTextResponse("persisted")

    app = Starlette(routes=[Route("/", intake, methods=["POST"])])
    app.add_middleware(
        LimitsMiddleware, max_request_bytes=max_bytes, rate_limit_per_minute=per_minute
    )
    return app


async def test_oversized_request_not_persisted() -> None:
    seen: list[bytes] = []
    app = app_with_limits(seen)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        small = await c.post("/", content=b"x" * 10)
        assert small.status_code == 200 and seen == [b"x" * 10]
        big = await c.post("/", content=b"x" * 1000)
        assert big.status_code == TOO_LARGE
        assert seen == [b"x" * 10]  # nothing reached the route, so nothing was persisted


async def test_flooding_peer_is_rate_limited_before_the_route() -> None:
    seen: list[bytes] = []
    app = app_with_limits(seen, per_minute=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        codes = [(await c.post("/", content=b"a")).status_code for _ in range(4)]
    assert codes == [200, 200, TOO_MANY, TOO_MANY]
    assert len(seen) == 2


Handler = Callable[[Request], Awaitable[PlainTextResponse]]
