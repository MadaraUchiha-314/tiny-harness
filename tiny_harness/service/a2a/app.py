"""The agent's HTTP surface (R14.1, R14.2; issue-36 R2, R4).

``build_routes`` returns the SDK's agent-card, JSON-RPC and HTTP+JSON routes plus the
harness's own (``GET /_monitor``, ``POST /a2a/push/{task_id}``, ``/ui``). The routes can be
built before the harness starts: they call a ``DeferredRequestHandler`` and read the card
through ``card_modifier``, both filled in at start. ``HarnessApp`` is the ASGI app a host
mounts: it answers ``503`` until the harness has started, refuses every request when it is
mounted somewhere other than its configured prefix, and starts the harness itself from the
``lifespan`` scope when it is the top-level app. ``create_app`` is the pre-issue-36 form over
a handler that already exists.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, MutableMapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from a2a.server.context import ServerCallContext
from a2a.server.events.event_queue import Event
from a2a.server.request_handlers import RequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes, create_rest_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetExtendedAgentCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    ListTaskPushNotificationConfigsRequest,
    ListTaskPushNotificationConfigsResponse,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
    TaskPushNotificationConfig,
)
from a2a.utils.errors import InternalError
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from tiny_harness.config import ServerConfig
from tiny_harness.errors import HarnessNotStartedError
from tiny_harness.jsontypes import JsonObject
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
from tiny_harness.service.o11y.logging import CURRENT_AGENT, drop_sdk_request_bodies

log = logging.getLogger("tiny_harness.a2a.app")

MonitorSource = Callable[[], Awaitable[JsonObject]]
CardSource = Callable[[], AgentCard]
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
            try:
                participant = self._resolver(request)
            except Exception as exc:
                # The host's auth error stays in the log: its text is not the client's to read
                # (issue-36 self-review 1, #4). Fail closed, with no fallback to the header.
                log.error("participant resolver failed: %s", type(exc).__name__, exc_info=exc)
                raise InternalError(message="the participant could not be resolved") from exc
        if participant:
            context.state[PARTICIPANT_STATE_KEY] = participant
        return context


@dataclass(frozen=True)
class RouteOptions:
    """Which of the harness's own routes and middleware a mounted agent has (issue-36 R4.4,
    R4.5). Each is on by default; turn one off when the host app does the job instead."""

    limits: bool = True  # request size and rate (max_request_bytes, rate_limit_per_minute)
    cors: bool = True  # CORSMiddleware when [server] cors_origins is set
    monitor: bool = True  # GET /_monitor
    push: bool = True  # POST /a2a/push/{task_id}; off: remote sub-tasks are followed
    ui: bool = True  # /ui when [server] ui_dir is set


ALL_ROUTES = RouteOptions()


class DeferredRequestHandler(RequestHandler):
    """A ``RequestHandler`` whose target is set when the harness starts, so the SDK's routes
    can be built (and mounted, and listed in OpenAPI) before it has."""

    def __init__(self) -> None:
        self.target: RequestHandler | None = None

    def _handler(self) -> RequestHandler:
        if self.target is None:
            raise HarnessNotStartedError("the agent is not started")
        return self.target

    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task | None:
        return await self._handler().on_get_task(params, context)

    async def on_list_tasks(
        self, params: ListTasksRequest, context: ServerCallContext
    ) -> ListTasksResponse:
        return await self._handler().on_list_tasks(params, context)

    async def on_cancel_task(
        self, params: CancelTaskRequest, context: ServerCallContext
    ) -> Task | None:
        return await self._handler().on_cancel_task(params, context)

    async def on_message_send(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> Task | Message:
        return await self._handler().on_message_send(params, context)

    async def on_message_send_stream(
        self, params: SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        stream = self._handler().on_message_send_stream(params, context)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def on_create_task_push_notification_config(
        self, params: TaskPushNotificationConfig, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        return await self._handler().on_create_task_push_notification_config(params, context)

    async def on_get_task_push_notification_config(
        self, params: GetTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> TaskPushNotificationConfig:
        return await self._handler().on_get_task_push_notification_config(params, context)

    async def on_subscribe_to_task(
        self, params: SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        stream = self._handler().on_subscribe_to_task(params, context)
        try:
            async for event in stream:
                yield event
        finally:
            await stream.aclose()

    async def on_list_task_push_notification_configs(
        self, params: ListTaskPushNotificationConfigsRequest, context: ServerCallContext
    ) -> ListTaskPushNotificationConfigsResponse:
        return await self._handler().on_list_task_push_notification_configs(params, context)

    async def on_delete_task_push_notification_config(
        self, params: DeleteTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> None:
        await self._handler().on_delete_task_push_notification_config(params, context)

    async def on_get_extended_agent_card(
        self, params: GetExtendedAgentCardRequest, context: ServerCallContext
    ) -> AgentCard:
        return await self._handler().on_get_extended_agent_card(params, context)


@dataclass(frozen=True)
class RouteGroups:
    """The agent's routes by kind, so the FastAPI helper can tag each group (issue-36 R3.3)."""

    card: list[BaseRoute]
    own: list[BaseRoute]  # /_monitor and /a2a/push/{task_id}
    ui: list[BaseRoute]  # the /ui mount, when configured
    jsonrpc: list[BaseRoute]
    rest: list[BaseRoute]

    def flat(self) -> list[BaseRoute]:
        """In today's order: the harness's own routes first (the SDK's REST routes carry path
        parameters at the root that would otherwise capture ``/_monitor`` and ``/ui/...``
        and answer 404), then JSON-RPC at ``/`` and HTTP+JSON."""
        return [*self.card, *self.own, *self.ui, *self.jsonrpc, *self.rest]


def build_route_groups(
    handler: RequestHandler,
    card: CardSource,
    *,
    config: ServerConfig,
    options: RouteOptions = ALL_ROUTES,
    monitor: MonitorSource | None = None,
    push: Callable[[], PushReceiver | None] | None = None,
    participant: ParticipantResolver | None = None,
) -> RouteGroups:
    drop_sdk_request_bodies()  # a request body may carry a push token (issue-27)
    builder = HarnessContextBuilder(participant)

    async def card_view(_placeholder: AgentCard) -> AgentCard:
        return card()

    async def monitor_view(request: Request) -> JSONResponse:
        snapshot: JsonObject = await monitor() if monitor is not None else {"tasks": []}
        return JSONResponse(snapshot)

    async def push_view(request: Request) -> Response:
        receiver = push() if push is not None else None
        if receiver is None:
            return Response(status_code=404)
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_PUSH_BYTES:
            return Response(status_code=413)  # refused before the body is read
        status = await receiver.receive(
            request.path_params["task_id"],
            request.headers.get(PUSH_TOKEN_HEADER),
            await request.body(),
        )
        return Response(status_code=status)

    own: list[BaseRoute] = []
    if options.monitor:
        own.append(Route("/_monitor", monitor_view, methods=["GET"]))
    if options.push and push is not None:
        own.append(Route(PUSH_PATH, push_view, methods=["POST"]))
    ui: list[BaseRoute] = []
    if options.ui and config.ui_dir is not None:  # the built web renderer, same origin
        ui.append(Mount("/ui", app=StaticFiles(directory=config.ui_dir, html=True)))
    return RouteGroups(
        card=list(create_agent_card_routes(AgentCard(), card_modifier=card_view)),
        own=own,
        ui=ui,
        jsonrpc=list(create_jsonrpc_routes(handler, rpc_url="/", context_builder=builder)),
        rest=list(create_rest_routes(handler, context_builder=builder)),
    )


def build_routes(
    handler: RequestHandler,
    card: CardSource,
    *,
    config: ServerConfig,
    options: RouteOptions = ALL_ROUTES,
    monitor: MonitorSource | None = None,
    push: Callable[[], PushReceiver | None] | None = None,
    participant: ParticipantResolver | None = None,
) -> list[BaseRoute]:
    """The agent's routes, flat and in order (``RouteGroups.flat``)."""
    return build_route_groups(
        handler,
        card,
        config=config,
        options=options,
        monitor=monitor,
        push=push,
        participant=participant,
    ).flat()


def wrap_middleware(app: ASGIApp, *, config: ServerConfig, options: RouteOptions) -> ASGIApp:
    """CORS inside the limits, as ``create_app`` always stacked them."""
    if options.cors and config.cors_origins:  # a web renderer served elsewhere
        app = CORSMiddleware(
            app,
            allow_origins=list(config.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["A2A-Version", "A2A-Extensions", "Content-Type", "X-Participant-Id"],
        )
    if options.limits:
        app = LimitsMiddleware(
            app,
            max_request_bytes=config.max_request_bytes,
            rate_limit_per_minute=config.rate_limit_per_minute,
        )
    return app


def create_app(
    handler: RequestHandler,
    card: AgentCard,
    *,
    config: ServerConfig,
    monitor: MonitorSource | None = None,
    push: PushReceiver | None = None,
) -> Starlette:
    """The server's app over a handler that already exists (the pre-issue-36 form)."""
    routes = build_routes(
        handler,
        lambda: card,
        config=config,
        monitor=monitor,
        push=(lambda: push) if push is not None else None,
    )
    app = Starlette(routes=routes)
    if config.cors_origins:
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


async def _json_error(send: Send, status: int, message: str) -> None:
    body = json.dumps({"error": message}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class HarnessApp:
    """The ASGI app a host mounts for one agent (issue-36 R2.1, R2.2, R2.5).

    - WHILE the harness is not started, every HTTP request is ``503`` and reaches no route.
    - On the first request, the mount is checked: ``root_path`` must end with the prefix
      the card was built for; otherwise every request is ``500`` and the mismatch is logged
      once, since a wrong mount means wrong URLs in the card.
    - As the top-level app it handles the ``lifespan`` scope and starts the harness itself,
      unless something else already has. Under a ``Mount`` Starlette never sends it.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        prefix: str,
        inner: ASGIApp,
        started: Callable[[], bool],
        lifespan: Callable[[], AbstractAsyncContextManager[object]] | None = None,
        check_path: bool = False,
    ) -> None:
        self.agent_id = agent_id
        self.prefix = prefix
        self._inner = inner
        self._started = started
        self._lifespan = lifespan
        self._check_path = check_path  # the router form: a prefix shows in the path
        self._mount_checked = False
        self._mount_error: str | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._run_lifespan(receive, send)
            return
        if scope["type"] != "http":
            await self._inner(scope, receive, send)
            return
        token = CURRENT_AGENT.set(self.agent_id)
        try:
            if not self._started():
                log.debug("request before agent %s started", self.agent_id)
                await _json_error(send, 503, f"agent {self.agent_id} is not started")
                return
            error = self._mount(scope)
            if error is not None:
                await _json_error(send, 500, error)
                return
            await self._inner(scope, receive, send)
        finally:
            CURRENT_AGENT.reset(token)

    def _mount(self, scope: MutableMapping[str, object]) -> str | None:
        if not self._mount_checked:
            self._mount_checked = True
            if self._check_path:
                mounted = str(scope.get("path", ""))
                ok = mounted == self.prefix or mounted.startswith(self.prefix + "/")
            else:
                # Exactly the prefix: a suffix match would accept /agents/b for /b, and an
                # unprefixed app mounted under a path would serve a card without that path
                # (issue-36 self-review 1, #6).
                mounted = str(scope.get("root_path", ""))
                ok = mounted == self.prefix
            if not ok:
                self._mount_error = (
                    f"agent {self.agent_id} is mounted at {mounted!r} "
                    f"but configured for {self.prefix or '/'!r}"
                )
                log.error("%s", self._mount_error)
        return self._mount_error

    async def _run_lifespan(self, receive: Receive, send: Send) -> None:
        message = await receive()
        assert message["type"] == "lifespan.startup"
        if self._lifespan is None or self._started():
            await send({"type": "lifespan.startup.complete"})
            await receive()  # lifespan.shutdown
            await send({"type": "lifespan.shutdown.complete"})
            return
        try:
            context = self._lifespan()
            await context.__aenter__()
        except Exception as exc:
            await send({"type": "lifespan.startup.failed", "message": str(exc)})
            return
        await send({"type": "lifespan.startup.complete"})
        await receive()  # lifespan.shutdown
        try:
            await context.__aexit__(None, None, None)
        except Exception as exc:
            await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
            return
        await send({"type": "lifespan.shutdown.complete"})


__all__ = [
    "ALL_ROUTES",
    "CardSource",
    "DeferredRequestHandler",
    "HarnessApp",
    "HarnessContextBuilder",
    "MonitorSource",
    "ParticipantResolver",
    "RouteGroups",
    "RouteOptions",
    "build_route_groups",
    "build_routes",
    "create_app",
    "wrap_middleware",
]
