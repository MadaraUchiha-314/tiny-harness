"""``create_app`` (R14.1, R14.2): the SDK's agent-card, JSON-RPC and REST routes on one
Starlette app behind the limits middleware, plus ``GET /_monitor`` (R16.3)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from a2a.server.context import ServerCallContext
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from tiny_harness.config import ServerConfig
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.handler import HarnessRequestHandler
from tiny_harness.service.a2a.middleware import LimitsMiddleware
from tiny_harness.service.a2a.task_store import PARTICIPANT_HEADER, PARTICIPANT_STATE_KEY

MonitorSource = Callable[[], Awaitable[JsonObject]]


class HarnessContextBuilder(DefaultServerCallContextBuilder):
    """The default builder plus the self-asserted participant (decision-003)."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        participant = request.headers.get(PARTICIPANT_HEADER)
        if participant:
            context.state[PARTICIPANT_STATE_KEY] = participant
        return context


def create_app(
    handler: HarnessRequestHandler,
    card: AgentCard,
    *,
    config: ServerConfig,
    monitor: MonitorSource | None = None,
) -> Starlette:
    builder = HarnessContextBuilder()
    routes: list[BaseRoute] = [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, rpc_url="/", context_builder=builder),
        *create_rest_routes(handler, context_builder=builder),
    ]

    async def monitor_view(request: Request) -> JSONResponse:
        snapshot: JsonObject = await monitor() if monitor is not None else {"tasks": []}
        return JSONResponse(snapshot)

    routes.append(Route("/_monitor", monitor_view, methods=["GET"]))
    if config.ui_dir is not None:  # the built web renderer, same origin as the API
        routes.append(Mount("/ui", app=StaticFiles(directory=config.ui_dir, html=True)))
    app = Starlette(routes=routes)
    if config.cors_origins:  # a web renderer served elsewhere (the Vite dev server)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["A2A-Version", "A2A-Extensions", "Content-Type", "X-Participant-Id"],
        )
    app.add_middleware(
        LimitsMiddleware,
        max_request_bytes=config.max_request_bytes,
        rate_limit_per_minute=config.rate_limit_per_minute,
    )
    return app


__all__ = ["HarnessContextBuilder", "MonitorSource", "create_app"]
