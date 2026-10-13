"""Feature: an agent mounted on a host Starlette app
Requirement: docs/specs/issue-36/requirements.md#requirement-1--start-a-harness-without-a-server,
#requirement-2--mount-an-agent-on-a-starlette-app, #requirement-4--customize-the-integration

One harness, or several, mounted under prefixes in the developer's own Starlette app and
served by the developer's own uvicorn, over the local Temporal dev server.
"""

from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from temporalio.testing import WorkflowEnvironment

from tests.integration.mount.conftest import (
    agent_settings,
    ask,
    env,
    free_port,
    reply_text,
    serving,
)
from tiny_harness.harness.models import FakeLLM, scripted
from tiny_harness.service import Harness, RouteOptions, harnesses_lifespan
from tiny_harness.service.claims import PROCESS_CLAIMS
from tiny_harness.service.o11y import configure_logging

__all__ = ["env"]

pytestmark = pytest.mark.asyncio(loop_scope="module")


def suffix() -> str:
    import uuid

    return uuid.uuid4().hex[:6]


async def test_a_harness_starts_from_a_host_lifespan_and_opens_no_port(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: A harness starts from a host lifespan and opens no port
        Given a host Starlette app with its own route and a harness mounted at /agents/a
        When the host's uvicorn starts the app and a client sends a message to the agent
        Then the agent answers at its prefix through the host's port
        And the agent's [server] bind address is never listened on
        And the Temporal client passed in still works after the harness stops
    """
    port, unused = free_port(), free_port()
    settings = agent_settings(tmp_path, f"a-{suffix()}", f"http://127.0.0.1:{port}/agents/a")
    settings = settings.model_copy(
        update={"server": settings.server.model_copy(update={"bind": f"127.0.0.1:{unused}"})}
    )
    harness = Harness(settings, client=env.client, llm=FakeLLM([scripted("Hello from a.")]))

    async def home(request: Request) -> PlainTextResponse:
        return PlainTextResponse("host")

    app = Starlette(
        routes=[Route("/", home), Mount("/agents/a", app=harness.asgi_app())],
        lifespan=harnesses_lifespan(harness),
    )
    async with serving(app, port) as origin:
        async with httpx.AsyncClient() as http:
            assert (await http.get(origin + "/")).text == "host"
        task = await ask(origin + "/agents/a", "hi")
        assert reply_text(task) == "Hello from a."
        with socket.socket() as probe:
            assert probe.connect_ex(("127.0.0.1", unused)) != 0
    assert not harness.started
    assert await env.client.count_workflows() is not None  # still open: not ours to close


async def test_an_agent_mounted_under_a_prefix_serves_its_card_with_prefixed_urls(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: An agent mounted under a prefix serves its card with prefixed URLs
        Given an agent whose base_url has no path and whose prefix is /agents/b
        When a client reads <origin>/agents/b/.well-known/agent-card.json
        Then every interface URL in the card starts with <origin>/agents/b
        And the card is named from the [agent] section
    """
    port = free_port()
    harness = Harness(
        agent_settings(tmp_path, f"b-{suffix()}", f"http://127.0.0.1:{port}"),
        client=env.client,
        prefix="/agents/b",
        llm=FakeLLM([]),
    )
    app = Starlette(routes=[Mount("/agents/b", app=harness.asgi_app())], lifespan=harness.lifespan)
    async with serving(app, port) as origin, httpx.AsyncClient() as http:
        card = (await http.get(origin + "/agents/b/.well-known/agent-card.json")).json()
        assert {i["url"] for i in card["supportedInterfaces"]} == {origin + "/agents/b/"}
        assert card["name"].startswith("Agent b-")


async def test_a_mounted_agent_answers_503_until_its_harness_has_started(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: A mounted agent answers 503 until its harness has started
        Given an agent mounted in a host app whose lifespan has not run
        When a client reads the card
        Then the answer is 503
        And once the harness has started, the same request is 200
    """
    harness = Harness(
        agent_settings(tmp_path, f"c-{suffix()}", "http://h/agents/c"),
        client=env.client,
        llm=FakeLLM([]),
    )
    app = Starlette(routes=[Mount("/agents/c", app=harness.asgi_app())])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://h") as http:
        path = "/agents/c/.well-known/agent-card.json"
        assert (await http.get(path)).status_code == 503
        async with harness:
            assert (await http.get(path)).status_code == 200
        assert (await http.get(path)).status_code == 503


async def test_an_agent_mounted_at_the_wrong_path_refuses_every_request(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: An agent mounted at the wrong path refuses every request
        Given an agent configured for /agents/d but mounted at /agents/x
        When a client reads the card twice
        Then both answers are 500 naming both paths
    """
    harness = Harness(
        agent_settings(tmp_path, f"d-{suffix()}", "http://h/agents/d"),
        client=env.client,
        llm=FakeLLM([]),
    )
    app = Starlette(routes=[Mount("/agents/x", app=harness.asgi_app())])
    async with (
        harness,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://h") as http,
    ):
        for _ in range(2):
            response = await http.get("/agents/x/.well-known/agent-card.json")
            assert response.status_code == 500
            assert "/agents/x" in response.json()["error"]
            assert "/agents/d" in response.json()["error"]


async def test_a_top_level_harness_app_starts_itself_from_the_server_lifespan(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: A top-level harness app starts itself from the server lifespan
        Given uvicorn serving harness.asgi_app() directly, with no host app
        When uvicorn starts and a client sends a message
        Then the harness was started by the lifespan scope and answers
        And it is stopped when uvicorn stops
    """
    port = free_port()
    harness = Harness(
        agent_settings(tmp_path, f"e-{suffix()}", f"http://127.0.0.1:{port}"),
        client=env.client,
        llm=FakeLLM([scripted("Top level.")]),
    )
    async with serving(harness.asgi_app(), port) as origin:
        assert harness.started
        assert reply_text(await ask(origin, "hi")) == "Top level."
    assert not harness.started


async def test_with_the_push_route_off_a_remote_sub_task_is_followed(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: With the push route off a remote sub-task is followed
        Given an agent with RouteOptions(push=False)
        When it starts
        Then it registers no push URL on remote tasks (it follows them)
        And POST /a2a/push/{id} is not one of its routes
    """
    harness = Harness(
        agent_settings(tmp_path, f"f-{suffix()}", "http://h/agents/f"),
        client=env.client,
        routes=RouteOptions(push=False),
        llm=FakeLLM([]),
    )
    app = Starlette(routes=[Mount("/agents/f", app=harness.asgi_app())])
    async with (
        harness,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://h") as http,
    ):
        assert harness._activities is not None  # pyright: ignore[reportPrivateUsage]
        assert harness._activities.push_base_url is None  # pyright: ignore[reportPrivateUsage]
        response = await http.post("/agents/f/a2a/push/t-1", content=b"{}")
        assert response.status_code != 401  # never reaches a push receiver


async def test_several_harnesses_start_and_stop_in_order_from_one_lifespan(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: Several harnesses start and stop in order from one lifespan
        Given three agents with their own ids, queues and stores
        When one lifespan runs all three
        Then all three are started and hold their claims inside it
        And all three are stopped and have released their claims after it
    """
    s = suffix()
    harnesses = [
        Harness(
            agent_settings(tmp_path, f"{n}-{s}", f"http://h/agents/{n}"),
            client=env.client,
            llm=FakeLLM([]),
        )
        for n in "xyz"
    ]
    before = PROCESS_CLAIMS.held()
    async with harnesses_lifespan(*harnesses)(object()):
        assert all(h.started for h in harnesses)
        assert PROCESS_CLAIMS.held() == before + 3
    assert not any(h.started for h in harnesses)
    assert PROCESS_CLAIMS.held() == before


async def test_each_log_line_names_the_agent_that_wrote_it(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: Each log line names the agent that wrote it
        Given two mounted agents and the harness's JSON logging
        When a client asks each agent for a task it does not have
        Then each agent's log lines carry its own agent id
    """
    stream = io.StringIO()
    configure_logging(stream=stream)
    s = suffix()
    a = Harness(
        agent_settings(tmp_path, f"la-{s}", "http://h/agents/a"), client=env.client, llm=FakeLLM([])
    )
    b = Harness(
        agent_settings(tmp_path, f"lb-{s}", "http://h/agents/b"), client=env.client, llm=FakeLLM([])
    )
    app = Starlette(
        routes=[Mount("/agents/a", app=a.asgi_app()), Mount("/agents/b", app=b.asgi_app())]
    )
    async with (
        a,
        b,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://h") as http,
    ):
        for name in ("a", "b"):
            await http.get(
                f"/agents/{name}/tasks/missing-{name}",
                headers={"X-Participant-Id": "alice", "A2A-Version": "1.0"},
            )
    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    for name, agent in (("a", a.agent_id), ("b", b.agent_id)):
        mine = [line for line in lines if f"missing-{name}" in json.dumps(line)]
        assert mine and all(line.get("agent") == agent for line in mine)
