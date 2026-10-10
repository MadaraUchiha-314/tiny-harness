"""``create_app`` (R14.1, R14.2): the SDK's agent-card, JSON-RPC and REST routes on one
Starlette app behind the limits middleware, plus ``GET /_monitor`` (R16.3)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from a2a.server.context import ServerCallContext
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route

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
    app = Starlette(routes=routes)
    app.add_middleware(
        LimitsMiddleware,
        max_request_bytes=config.max_request_bytes,
        rate_limit_per_minute=config.rate_limit_per_minute,
    )
    return app


__all__ = ["HarnessContextBuilder", "MonitorSource", "create_app"]
