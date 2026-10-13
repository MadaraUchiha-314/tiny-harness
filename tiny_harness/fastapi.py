"""An agent as a FastAPI router (issue-36 R3): ``app.include_router(harness_router(harness))``.

The router carries the harness's lifespan (FastAPI merges a router's lifespan into the
app's in ``include_router``) and its routes, tagged per agent and annotated with the A2A
request bodies by a2a-sdk's own FastAPI helper, so they show in the app's ``/docs``.

A router cannot carry ASGI middleware, and FastAPI ignores an ``APIRoute`` subclass's
``app``, so the 503 gate, the mount check and the limits are router dependencies here. CORS
is application-wide in Starlette and FastAPI drops a ``Mount`` from a router, so
``[server] cors_origins`` and ``ui_dir`` are not served by the router: its lifespan warns
when either is set. Install with ``pip install 'tiny_harness[fastapi]'``.

    harness = Harness(Settings.load(Path("support.toml")), prefix="/agents/support")
    app = FastAPI()
    app.include_router(harness_router(harness))  # no further prefix: the harness has it
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from enum import Enum

try:
    from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
    from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
    from fastapi.routing import APIRoute
except ImportError as exc:  # pragma: no cover - exercised by the packaging test
    raise ImportError(
        "tiny_harness.fastapi needs FastAPI: pip install 'tiny_harness[fastapi]'"
    ) from exc
from starlette.routing import BaseRoute, Route, compile_path

from tiny_harness.service.a2a.middleware import TokenBucket
from tiny_harness.service.harness import Harness, Lifespan
from tiny_harness.service.o11y.logging import CURRENT_AGENT

log = logging.getLogger("tiny_harness.fastapi")


class _Gate:
    """The router's per-request checks: started, mounted where configured, and the agent
    named on the request's log lines."""

    def __init__(self, harness: Harness, paths: Sequence[str]) -> None:
        self.harness = harness
        # The full paths the routes must be served at: the harness prefix and each route's
        # own path, exactly (issue-36 self-review 1, #6).
        self.paths = [compile_path(harness.prefix + path)[0] for path in paths]
        self.checked = False
        self.error: str | None = None

    async def __call__(self, request: Request) -> AsyncGenerator[None]:
        token = CURRENT_AGENT.set(self.harness.agent_id)
        try:
            if not self.harness.started:
                raise HTTPException(503, f"agent {self.harness.agent_id} is not started")
            if not self.checked:
                self.checked = True
                # The full path, root_path included: a root_path that is not in the card's
                # URL means the card is wrong (issue-36 self-review 2, #1).
                path = request.url.path
                if not any(pattern.fullmatch(path) for pattern in self.paths):
                    self.error = (
                        f"agent {self.harness.agent_id} is mounted at {path!r} "
                        f"but configured for {self.harness.prefix or '/'!r}"
                    )
                    log.error("%s", self.error)
            if self.error is not None:
                raise HTTPException(500, self.error)
            yield
        finally:
            # Self-review 1, #7: no agent left on the caller. A teardown in another context
            # cannot reset it, and that context ends with the request anyway.
            with contextlib.suppress(ValueError):
                CURRENT_AGENT.reset(token)


class _Limits:
    """``max_request_bytes`` and ``rate_limit_per_minute`` for the router's routes."""

    def __init__(self, harness: Harness) -> None:
        server = harness.settings.server
        self.max_bytes = server.max_request_bytes
        self.bucket = TokenBucket(server.rate_limit_per_minute)

    async def __call__(self, request: Request) -> None:
        peer = request.client.host if request.client is not None else "unknown"
        if not self.bucket.take(peer):
            raise HTTPException(429, "rate limit exceeded")
        declared = request.headers.get("content-length")
        if declared is not None:
            if declared.isdigit() and int(declared) > self.max_bytes:
                raise HTTPException(413, "request too large")
            return
        if request.method not in ("POST", "PUT", "PATCH"):
            return
        body = bytearray()
        async for chunk in request.stream():  # no declared length: read it, bounded
            body.extend(chunk)
            if len(body) > self.max_bytes:
                raise HTTPException(413, "request too large")
        request._body = bytes(body)  # pyright: ignore[reportPrivateUsage]  # the endpoint reads it


def harness_router(harness: Harness, *, tags: Sequence[str] | None = None) -> APIRouter:
    """The harness's routes as an ``APIRouter`` with its lifespan. Include it with
    ``app.include_router(router)`` and no further prefix: the prefix is the harness's own,
    and a request under any other path is refused with 500."""
    tag_list: list[str | Enum] = list(tags) if tags is not None else [f"A2A: {harness.agent_id}"]
    groups = harness.route_groups()
    own_paths = [
        r.path
        for r in [*groups.card, *groups.own, *groups.jsonrpc, *groups.rest]
        if isinstance(r, Route)
    ]
    dependencies = [Depends(_Gate(harness, own_paths))]
    if harness.route_options.limits:
        dependencies.append(Depends(_Limits(harness)))
    router = APIRouter(
        prefix=harness.prefix, lifespan=_router_lifespan(harness), dependencies=dependencies
    )
    scratch = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    add_a2a_routes_to_fastapi(
        scratch,
        agent_card_routes=groups.card,
        jsonrpc_routes=groups.jsonrpc,
        rest_routes=groups.rest,
    )
    for route in [*_api_routes(scratch.routes), *groups.own]:
        _add(router, route, tag_list)
    return router


def _api_routes(routes: Sequence[BaseRoute]) -> list[APIRoute]:
    return [r for r in routes if isinstance(r, APIRoute)]


def _add(router: APIRouter, route: BaseRoute, tags: list[str | Enum]) -> None:
    """Re-add ``route`` with ``add_api_route``: that call applies the router's prefix."""
    if isinstance(route, APIRoute):
        router.add_api_route(
            route.path,
            route.endpoint,
            methods=sorted(route.methods or ()),
            tags=tags,
            summary=route.summary,
            description=route.description,
            openapi_extra=route.openapi_extra,
        )
    elif isinstance(route, Route):
        methods = sorted(m for m in route.methods or ("GET",) if m != "HEAD")
        router.add_api_route(route.path, route.endpoint, methods=methods, tags=tags)


def _router_lifespan(harness: Harness) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: object) -> AsyncGenerator[None]:
        server = harness.settings.server
        if server.cors_origins and harness.route_options.cors:
            log.warning(
                "agent %s: [server] cors_origins is not applied by a FastAPI router; "
                "add CORSMiddleware to your app",
                harness.agent_id,
            )
        if server.ui_dir is not None and harness.route_options.ui:
            log.warning(
                "agent %s: [server] ui_dir is not served by a FastAPI router; "
                "mount StaticFiles on your app",
                harness.agent_id,
            )
        async with harness:
            yield

    return lifespan


__all__ = ["harness_router"]
