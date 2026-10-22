"""The A2A server in-process over the Temporal test environment (T2)."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
import pytest_asyncio
from a2a.client import ClientConfig, create_client
from a2a.client.client import Client as A2AClient
from a2a.server.tasks import BasePushNotificationSender
from a2a.types import AgentCard
from pydantic import HttpUrl
from starlette.applications import Starlette
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from tests.integration.durable.conftest import Harness, env
from tests.integration.streaming_asgi import StreamingASGITransport
from tiny_harness.config import ServerConfig
from tiny_harness.harness.agents import SELF_AGENT_ID, RemoteAgent
from tiny_harness.harness.entities import RegistryEntry
from tiny_harness.harness.media import MediaIntake
from tiny_harness.harness.models import LLMResponse
from tiny_harness.service.a2a import (
    HarnessExecutor,
    HarnessRequestHandler,
    PollingEventBridge,
    PushReceiver,
    PushSink,
    StorePushConfigStore,
    TemporalTaskStore,
    build_agent_card,
    create_app,
)
from tiny_harness.service.a2a.card import AgentDescription
from tiny_harness.service.durable.models import WorkflowConfig

SELF_URL = "http://harness"


@dataclass
class Server:
    """One server process: app, SDK client over ASGI, the worker, captured push posts. As
    ``build_runtime`` does, the harness is registered as its own agent ``self``, reached
    through its own app (issue-34 R7.1)."""

    harness: Harness
    app: Starlette
    card: AgentCard
    worker: Worker
    handler: HarnessRequestHandler
    pushes: list[httpx.Request] = field(default_factory=lambda: list[httpx.Request]())
    http: httpx.AsyncClient | None = None
    client: A2AClient | None = None
    blocking_client: A2AClient | None = None
    me: RemoteAgent | None = None
    me_http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Server:
        self.me_http = httpx.AsyncClient(
            transport=StreamingASGITransport(self.app), base_url=SELF_URL, timeout=60
        )
        self.me = RemoteAgent.from_card(SELF_AGENT_ID, self.card, http=self.me_http)
        await self.harness.registry.add(
            RegistryEntry(ref=self.me.ref, instance=self.me), override=True
        )
        await self.worker.__aenter__()
        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://harness",
            timeout=60,
            headers={"X-Participant-Id": "alice"},  # the perimeter's assertion, overridden per call
        )
        self.client = await create_client(
            "http://harness",
            client_config=ClientConfig(
                httpx_client=self.http, streaming=True, supported_protocol_bindings=["JSONRPC"]
            ),
        )
        self.blocking_client = await create_client(
            "http://harness",
            client_config=ClientConfig(
                httpx_client=self.http, streaming=False, supported_protocol_bindings=["JSONRPC"]
            ),
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.client is not None:
            await self.client.close()
        if self.http is not None:
            await self.http.aclose()
        await self.worker.__aexit__(None, None, None)
        if self.me is not None:
            await self.me.close()
        if self.me_http is not None:
            await self.me_http.aclose()

    def a2a(self) -> A2AClient:
        assert self.client is not None
        return self.client

    def blocking(self) -> A2AClient:
        """A non-streaming client: ``SendMessage`` rather than ``SendStreamingMessage``."""
        assert self.blocking_client is not None
        return self.blocking_client


async def make_server(
    environment: WorkflowEnvironment,
    responses: Sequence[LLMResponse],
    *,
    task_queue: str,
    harness: Harness | None = None,
    sticky: bool = True,
    push_to: Callable[[httpx.Request], Awaitable[httpx.Response]] | None = None,
    push_base_url: str | None = None,
    media_intake: MediaIntake | None = None,
) -> Server:
    """``push_to`` delivers this server's outbound pushes (default: captured, ``200``);
    ``push_base_url`` is where this server's stand-ins ask remote agents to push."""
    h = harness or await Harness(list(responses)).bind()
    pushes: list[httpx.Request] = []

    async def capture(request: httpx.Request) -> httpx.Response:
        pushes.append(request)
        if push_to is not None:
            return await push_to(request)
        return httpx.Response(200)

    push_http = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    push_store = StorePushConfigStore(h.store)
    bridge = PollingEventBridge(environment.client, interval=timedelta(milliseconds=50))
    card = build_agent_card(AgentDescription(), "http://harness")
    executor = HarnessExecutor(
        environment.client,
        task_queue=task_queue,
        bridge=bridge,
        config=WorkflowConfig(search_attributes=False),
        media_intake=media_intake,
    )
    handler = HarnessRequestHandler(
        bridge=bridge,
        agent_executor=executor,
        task_store=TemporalTaskStore(environment.client, h.store),
        agent_card=card,
        push_config_store=push_store,
        push_sender=BasePushNotificationSender(push_http, push_store),
    )
    app = create_app(
        handler,
        card,
        config=ServerConfig(base_url=HttpUrl("http://harness")),
        push=PushReceiver(environment.client),
    )
    worker = h.worker(
        environment.client, task_queue, sink=PushSink(push_store, push_http), sticky=sticky
    )
    assert h.activities is not None
    h.activities.push_base_url = push_base_url
    return Server(harness=h, app=app, card=card, worker=worker, handler=handler, pushes=pushes)


@asynccontextmanager
async def self_hosted(
    environment: WorkflowEnvironment,
    responses: Sequence[LLMResponse] = (),
    *,
    task_queue: str,
    harness: Harness | None = None,
) -> AsyncGenerator[Server]:
    """This harness serving its own A2A app (``self`` registered over it, issue-34 R7.1),
    with its pushes delivered to its own push endpoint, as over HTTP in production: a
    child it creates leaves through its own A2A interface and its changes come back in."""
    apps: dict[str, Starlette] = {}

    async def to_self(request: httpx.Request) -> httpx.Response:
        response = await httpx.ASGITransport(app=apps["self"]).handle_async_request(request)
        await response.aread()
        return response

    server = await make_server(
        environment,
        responses,
        task_queue=task_queue,
        harness=harness,
        push_to=to_self,
        push_base_url=SELF_URL,
    )
    apps["self"] = server.app
    async with server:
        yield server


__all__ = ["SELF_URL", "Server", "env", "make_server", "self_hosted"]


@pytest_asyncio.fixture(loop_scope="module")
async def unused() -> AsyncIterator[None]:
    yield None
