"""Feature: A2A server
Requirement: docs/specs/issue-3/requirements.md#R20, #R16

The harness's own routes (the built web renderer under /ui, the monitor view) must be
matched before the SDK's REST routes, whose root-level path parameters otherwise capture
them and answer 404.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx
from a2a.server.tasks import BasePushNotificationSender
from pydantic import HttpUrl, SecretStr
from temporalio.client import Client

from tiny_harness.config import ServerConfig
from tiny_harness.harness.persistence import PushTokenCipher, SqliteStore
from tiny_harness.harness.security import Redactor
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a import (
    HarnessExecutor,
    HarnessRequestHandler,
    PollingEventBridge,
    StorePushConfigStore,
    TemporalTaskStore,
    build_agent_card,
    create_app,
)
from tiny_harness.service.a2a.card import AgentDescription
from tiny_harness.service.durable.models import WorkflowConfig

PUSH_KEY = SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")


def handler() -> HarnessRequestHandler:
    """A handler over a client that is never called: /ui and /_monitor reach no workflow."""
    client = cast(Client, object())
    store = SqliteStore(":memory:")
    push_store = StorePushConfigStore(store, PushTokenCipher(PUSH_KEY))
    bridge = PollingEventBridge(client)
    return HarnessRequestHandler(
        bridge=bridge,
        agent_executor=HarnessExecutor(
            client, task_queue="tq", bridge=bridge, config=WorkflowConfig(), redactor=Redactor()
        ),
        task_store=TemporalTaskStore(client, store),
        agent_card=build_agent_card(AgentDescription(), "http://harness/"),
        push_config_store=push_store,
        push_sender=BasePushNotificationSender(httpx.AsyncClient(), push_store),
    )


async def test_the_web_renderer_and_the_monitor_are_served_beside_the_sdk_routes(
    tmp_path: Path,
) -> None:
    """
    Scenario: the web renderer and the monitor are served beside the SDK routes
        Given a server configured with a built web renderer directory
        When /ui/, /ui/index.html and /_monitor are requested
        Then the renderer's index and the monitor snapshot are returned, not the SDK's 404
        And the agent card is still served
    """
    (tmp_path / "index.html").write_text("<!doctype html><title>tiny-harness web</title>")

    async def monitor() -> JsonObject:
        return {"tasks": [{"id": "t1"}]}

    card = build_agent_card(AgentDescription(), "http://harness/")
    app = create_app(
        handler(),
        card,
        config=ServerConfig(base_url=HttpUrl("http://harness"), ui_dir=tmp_path),
        monitor=monitor,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://harness"
    ) as http:
        index = await http.get("/ui/")
        assert index.status_code == 200 and "tiny-harness web" in index.text
        assert (await http.get("/ui/index.html")).status_code == 200
        snapshot = await http.get("/_monitor")
        assert snapshot.status_code == 200 and snapshot.json() == {"tasks": [{"id": "t1"}]}
        assert (await http.get("/.well-known/agent-card.json")).status_code == 200
