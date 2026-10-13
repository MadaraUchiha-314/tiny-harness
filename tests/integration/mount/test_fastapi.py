"""Feature: an agent included in a host FastAPI app
Requirement: docs/specs/issue-36/requirements.md#R3

``app.include_router(harness_router(harness))``: the harness starts with the app's lifespan,
its routes show in the app's OpenAPI document tagged per agent, and the 503 gate, the mount
check and the limits apply as router dependencies.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from temporalio.testing import WorkflowEnvironment

from tests.integration.mount.conftest import (
    agent_settings,
    ask,
    env,
    free_port,
    reply_text,
    serving,
)
from tiny_harness.fastapi import harness_router
from tiny_harness.harness.models import FakeLLM, scripted
from tiny_harness.service import Harness

__all__ = ["env"]

pytestmark = pytest.mark.asyncio(loop_scope="module")


def suffix() -> str:
    return uuid.uuid4().hex[:6]


async def test_a_fastapi_app_includes_an_agent_router_and_lists_its_routes_in_openapi(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: A FastAPI app includes an agent router and lists its routes in OpenAPI
        Given a FastAPI app with its own route and two agents' routers
        When uvicorn starts the app
        Then both harnesses are started by the app's lifespan
        And a message to each agent is answered at its prefix
        And the OpenAPI document lists each agent's routes under its own tag
        And both harnesses are stopped with the app
    """
    port, s = free_port(), suffix()
    a = Harness(
        agent_settings(tmp_path, f"fa-{s}", f"http://127.0.0.1:{port}/agents/a"),
        client=env.client,
        llm=FakeLLM([scripted("From a.")]),
    )
    b = Harness(
        agent_settings(tmp_path, f"fb-{s}", f"http://127.0.0.1:{port}/agents/b"),
        client=env.client,
        llm=FakeLLM([scripted("From b.")]),
    )
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"ok": "yes"}

    app.include_router(harness_router(a))
    app.include_router(harness_router(b))
    async with serving(app, port) as origin:
        assert a.started and b.started
        assert reply_text(await ask(origin + "/agents/a", "hi")) == "From a."
        assert reply_text(await ask(origin + "/agents/b", "hi")) == "From b."
        async with httpx.AsyncClient() as http:
            assert (await http.get(origin + "/health")).json() == {"ok": "yes"}
            schema = (await http.get(origin + "/openapi.json")).json()
            card = (await http.get(origin + "/agents/b/.well-known/agent-card.json")).json()
    assert {i["url"] for i in card["supportedInterfaces"]} == {origin + "/agents/b/"}
    tags: dict[str, set[str]] = {}
    for path, operations in schema["paths"].items():
        for operation in operations.values():
            for tag in operation.get("tags", []):
                tags.setdefault(tag, set()).add(path)
    assert "/agents/a/" in tags[f"A2A: {a.agent_id}"]
    assert "/agents/b/message:send" in tags[f"A2A: {b.agent_id}"]
    assert "/agents/a/.well-known/agent-card.json" in tags[f"A2A: {a.agent_id}"]
    assert not a.started and not b.started


async def test_a_router_answers_503_before_start_and_enforces_its_limits(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Requirement: docs/specs/issue-36/requirements.md#R3, #R4

    Scenario: A router answers 503 before start and enforces its limits
        Given a FastAPI app with an agent's router whose harness has not started
        When a client reads the card
        Then the answer is 503
        And once started, a body over max_request_bytes is refused with 413
    """
    settings = agent_settings(tmp_path, f"fl-{suffix()}", "http://h/agents/l")
    settings = settings.model_copy(
        update={"server": settings.server.model_copy(update={"max_request_bytes": 64})}
    )
    harness = Harness(settings, client=env.client, llm=FakeLLM([]))
    app = FastAPI()
    app.include_router(harness_router(harness))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://h"
    ) as http:
        assert (await http.get("/agents/l/.well-known/agent-card.json")).status_code == 503
        async with harness:
            assert (await http.get("/agents/l/.well-known/agent-card.json")).status_code == 200
            big = await http.post("/agents/l/", content=b"x" * 200)
            assert big.status_code == 413


async def test_a_router_included_under_another_prefix_refuses_every_request(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Requirement: docs/specs/issue-36/requirements.md#R3

    Scenario: A router included under another prefix refuses every request
        Given an agent configured for /agents/p whose router is included with prefix /extra
        When a client reads the card at /extra/agents/p
        Then every answer is 500 naming both paths
    """
    harness = Harness(
        agent_settings(tmp_path, f"fp-{suffix()}", "http://h/agents/p"),
        client=env.client,
        llm=FakeLLM([]),
    )
    app = FastAPI()
    app.include_router(harness_router(harness), prefix="/extra")
    async with (
        harness,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://h") as http,
    ):
        for _ in range(2):
            response = await http.get("/extra/agents/p/.well-known/agent-card.json")
            assert response.status_code == 500
            assert "/extra/agents/p" in response.json()["detail"]
