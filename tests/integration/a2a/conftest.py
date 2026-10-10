"""The A2A server in-process over the Temporal test environment (T2)."""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
import pytest_asyncio
from a2a.client import ClientConfig, create_client
from a2a.client.client import Client as A2AClient
from a2a.server.tasks import BasePushNotificationSender
from a2a.types import AgentCard
from pydantic import HttpUrl, SecretStr
from starlette.applications import Starlette
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from tests.integration.durable.conftest import Harness, env
from tiny_harness.config import ServerConfig
from tiny_harness.harness.models import LLMResponse
from tiny_harness.harness.persistence import PushTokenCipher
from tiny_harness.service.a2a import (
    HarnessExecutor,
    HarnessRequestHandler,
    PollingEventBridge,
    PushSink,
    StorePushConfigStore,
    TemporalTaskStore,
    build_agent_card,
    create_app,
)
from tiny_harness.service.a2a.card import AgentDescription
from tiny_harness.service.durable.models import WorkflowConfig

PUSH_KEY = SecretStr(base64.b64encode(os.urandom(32)).decode())


@dataclass
class Server:
    """One server process: app, SDK client over ASGI, the worker, captured push posts."""

    harness: Harness
    app: Starlette
    card: AgentCard
    worker: Worker
    handler: HarnessRequestHandler
    pushes: list[httpx.Request] = field(default_factory=lambda: list[httpx.Request]())
    http: httpx.AsyncClient | None = None
    client: A2AClient | None = None
    blocking_client: A2AClient | None = None

    async def __aenter__(self) -> Server:
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
) -> Server:
    h = harness or await Harness(list(responses)).bind()
    pushes: list[httpx.Request] = []

    async def capture(request: httpx.Request) -> httpx.Response:
        pushes.append(request)
        return httpx.Response(200)

    push_http = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    push_store = StorePushConfigStore(h.store, PushTokenCipher(PUSH_KEY))
    bridge = PollingEventBridge(environment.client, interval=timedelta(milliseconds=50))
    card = build_agent_card(AgentDescription(), "http://harness")
    executor = HarnessExecutor(
        environment.client,
        task_queue=task_queue,
        bridge=bridge,
        config=WorkflowConfig(search_attributes=False),
    )
    handler = HarnessRequestHandler(
        bridge=bridge,
        agent_executor=executor,
        task_store=TemporalTaskStore(environment.client, h.store),
        agent_card=card,
        push_config_store=push_store,
        push_sender=BasePushNotificationSender(push_http, push_store),
    )
    app = create_app(handler, card, config=ServerConfig(base_url=HttpUrl("http://harness")))
    worker = h.worker(environment.client, task_queue, sink=PushSink(push_store, push_http))
    return Server(harness=h, app=app, card=card, worker=worker, handler=handler, pushes=pushes)


__all__ = ["PUSH_KEY", "Server", "env", "make_server"]


@pytest_asyncio.fixture(loop_scope="module")
async def unused() -> AsyncIterator[None]:
    yield None
