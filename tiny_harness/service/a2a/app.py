"""``create_app`` (R14.1, R14.2): the SDK's agent-card, JSON-RPC and REST routes on one
Starlette app behind the limits middleware, plus ``GET /_monitor`` (R16.3) and, when a
receiver is given, ``POST /a2a/push/{task_id}`` for remote tasks' pushes (issue-27 R2)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from a2a.server.context import ServerCallContext
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from tiny_harness.config import ServerConfig
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.handler import HarnessRequestHandler
from tiny_harness.service.a2a.middleware import LimitsMiddleware
from tiny_harness.service.a2a.push import (
    MAX_PUSH_BYTES,
    PUSH_PATH,
    PUSH_TOKEN_HEADER,
    PushReceiver,
)
from tiny_harness.service.a2a.task_store import (
    PARTICIPANT_HEADER,
    PARTICIPANT_STATE_KEY,
    STRICT_STATE_KEY,
)
from tiny_harness.service.o11y.logging import drop_sdk_request_bodies

MonitorSource = Callable[[], Awaitable[JsonObject]]
ParticipantResolver = Callable[[Request], str | None]
"""The host app's identity hook (issue-36 R4.1): the request's authenticated participant id,
or ``None``. Synchronous, as the SDK's context builder is; the host's auth middleware has
already run."""


class HarnessContextBuilder(DefaultServerCallContextBuilder):
    """The default builder plus the participant: the self-asserted ``X-Participant-Id``
    header (decision-003), or, with a ``resolver``, the host app's answer and never the
    header (issue-36 R4.2). A resolver that raises fails the request; there is no fallback."""

    def __init__(self, resolver: ParticipantResolver | None = None) -> None:
        super().__init__()
        self._resolver = resolver

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        if self._resolver is None:
            participant = request.headers.get(PARTICIPANT_HEADER)
        else:
            context.state[STRICT_STATE_KEY] = True
            participant = self._resolver(request)
        if participant:
            context.state[PARTICIPANT_STATE_KEY] = participant
        return context


def create_app(
    handler: HarnessRequestHandler,
    card: AgentCard,
    *,
    config: ServerConfig,
    monitor: MonitorSource | None = None,
    push: PushReceiver | None = None,
) -> Starlette:
    drop_sdk_request_bodies()  # a request body may carry a push token (issue-27)
    builder = HarnessContextBuilder()

    async def monitor_view(request: Request) -> JSONResponse:
        snapshot: JsonObject = await monitor() if monitor is not None else {"tasks": []}
        return JSONResponse(snapshot)

    async def push_view(request: Request) -> Response:
        assert push is not None
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_PUSH_BYTES:
            return Response(status_code=413)  # refused before the body is read
        status = await push.receive(
            request.path_params["task_id"],
            request.headers.get(PUSH_TOKEN_HEADER),
            await request.body(),
        )
        return Response(status_code=status)

    # The harness's own routes go first: the SDK's REST routes carry path parameters at
    # the root that would otherwise capture /_monitor and /ui/... and answer 404.
    routes: list[BaseRoute] = [
        *create_agent_card_routes(card),
        Route("/_monitor", monitor_view, methods=["GET"]),
    ]
    if push is not None:
        routes.append(Route(PUSH_PATH, push_view, methods=["POST"]))
    if config.ui_dir is not None:  # the built web renderer, same origin as the API
        routes.append(Mount("/ui", app=StaticFiles(directory=config.ui_dir, html=True)))
    routes.extend(create_jsonrpc_routes(handler, rpc_url="/", context_builder=builder))
    routes.extend(create_rest_routes(handler, context_builder=builder))
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


__all__ = ["HarnessContextBuilder", "MonitorSource", "ParticipantResolver", "create_app"]
