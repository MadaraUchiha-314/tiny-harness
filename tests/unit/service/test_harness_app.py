"""``HarnessApp`` and ``build_routes`` (issue-36 R2.1, R2.2, R2.5, R4.4, R4.5; abuse
case 5): a mounted agent answers 503 until started and reaches no route; a wrong mount is
refused; the top-level app starts its harness from the lifespan; each route option removes
exactly its route or middleware."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import HttpUrl
from starlette.applications import Starlette
from starlette.routing import Mount

from tiny_harness.config import ServerConfig
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.app import (
    ALL_ROUTES,
    DeferredRequestHandler,
    HarnessApp,
    RouteOptions,
    build_routes,
    wrap_middleware,
)
from tiny_harness.service.a2a.card import AgentDescription, build_agent_card
from tiny_harness.service.a2a.middleware import LimitsMiddleware

CONFIG = ServerConfig(base_url=HttpUrl("http://h/agents/a"), cors_origins=("http://ui",))


class Flag:
    def __init__(self, value: bool) -> None:
        self.value = value
        self.monitor_calls = 0

    def __call__(self) -> bool:
        return self.value


def harness_app(
    started: Flag,
    *,
    prefix: str = "/agents/a",
    options: RouteOptions = ALL_ROUTES,
    ui_dir: Path | None = None,
) -> HarnessApp:
    card = build_agent_card(AgentDescription(), "http://h/agents/a")

    async def monitor() -> JsonObject:
        started.monitor_calls += 1
        return {"tasks": []}

    config = CONFIG.model_copy(update={"ui_dir": ui_dir})
    routes = build_routes(
        DeferredRequestHandler(), lambda: card, config=config, options=options, monitor=monitor
    )
    inner = wrap_middleware(Starlette(routes=routes), config=config, options=options)
    return HarnessApp(agent_id="a", prefix=prefix, inner=inner, started=started)


def host(app: HarnessApp, at: str = "/agents/a") -> httpx.AsyncClient:
    outer = Starlette(routes=[Mount(at, app=app)])
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=outer), base_url="http://h")


async def test_before_start_every_route_is_503_and_reaches_nothing() -> None:
    flag = Flag(False)
    async with host(harness_app(flag)) as http:
        for path in ("/agents/a/.well-known/agent-card.json", "/agents/a/_monitor"):
            response = await http.get(path)
            assert response.status_code == 503
            assert response.json() == {"error": "agent a is not started"}
        assert (await http.post("/agents/a/", json={})).status_code == 503
    assert flag.monitor_calls == 0


async def test_once_started_the_card_is_served_under_the_prefix() -> None:
    async with host(harness_app(Flag(True))) as http:
        response = await http.get("/agents/a/.well-known/agent-card.json")
        assert response.status_code == 200
        urls = {i["url"] for i in response.json()["supportedInterfaces"]}
        assert urls == {"http://h/agents/a/"}


async def test_a_wrong_mount_refuses_every_request() -> None:
    async with host(harness_app(Flag(True)), at="/agents/b") as http:
        for _ in range(2):
            response = await http.get("/agents/b/.well-known/agent-card.json")
            assert response.status_code == 500
            assert "mounted at '/agents/b'" in response.json()["error"]


@pytest.mark.parametrize(
    ("options", "missing"),
    [
        (RouteOptions(monitor=False), "/_monitor"),
        (RouteOptions(ui=False), "/ui/"),
    ],
)
async def test_a_route_option_removes_its_route(
    tmp_path: Path, options: RouteOptions, missing: str
) -> None:
    (tmp_path / "index.html").write_text("<title>ui</title>")
    async with host(harness_app(Flag(True), options=options, ui_dir=tmp_path)) as http:
        assert (await http.get("/agents/a" + missing)).status_code != 200
    async with host(harness_app(Flag(True), ui_dir=tmp_path)) as http:
        assert (await http.get("/agents/a" + missing)).status_code == 200


def test_limits_and_cors_can_each_be_turned_off() -> None:
    inner = Starlette()
    assert isinstance(
        wrap_middleware(inner, config=CONFIG, options=RouteOptions()), LimitsMiddleware
    )
    assert (
        wrap_middleware(inner, config=CONFIG, options=RouteOptions(limits=False, cors=False))
        is inner
    )
    no_limits = wrap_middleware(inner, config=CONFIG, options=RouteOptions(limits=False))
    assert type(no_limits).__name__ == "CORSMiddleware"


async def test_the_top_level_app_starts_its_harness_from_the_lifespan() -> None:
    flag = Flag(False)
    events: list[str] = []

    @asynccontextmanager
    async def lifespan() -> AsyncGenerator[None]:
        flag.value = True
        events.append("start")
        yield
        events.append("stop")

    app = harness_app(flag, prefix="")
    app._lifespan = lifespan  # pyright: ignore[reportPrivateUsage]
    sent: list[str] = []
    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

    async def receive() -> dict[str, str]:
        return next(messages)

    async def send(message: dict[str, str]) -> None:
        sent.append(message["type"])

    await app({"type": "lifespan"}, receive, send)  # type: ignore[arg-type]
    assert events == ["start", "stop"]
    assert sent == ["lifespan.startup.complete", "lifespan.shutdown.complete"]


@pytest.mark.parametrize(("prefix", "mounted_at"), [("", "/agents/a"), ("/a", "/agents/a")])
async def test_only_the_exact_prefix_passes_the_mount_check(prefix: str, mounted_at: str) -> None:
    """Self-review round 1, finding 6: no suffix match, and no unprefixed app under a path."""
    async with host(harness_app(Flag(True), prefix=prefix), at=mounted_at) as http:
        response = await http.get(f"{mounted_at}/.well-known/agent-card.json")
        assert response.status_code == 500
