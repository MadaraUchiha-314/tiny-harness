"""Feature: the host app's authentication names the participant
Requirement: docs/specs/issue-36/requirements.md#R4 (Security considerations, abuse case 1)

A host app authenticates with its own middleware; the agent's participant resolver reads
the authenticated user. A client-sent ``X-Participant-Id`` header, or a message's own
``participant_id`` claim, never stands in for it.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from a2a.types import Task
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.routing import Mount
from starlette.types import ASGIApp, Receive, Scope, Send
from temporalio.testing import WorkflowEnvironment

from tests.integration.mount.conftest import agent_settings, env
from tiny_harness.harness.core import HarnessTask, Role
from tiny_harness.harness.models import FakeLLM, scripted
from tiny_harness.service import Harness

__all__ = ["env"]

pytestmark = pytest.mark.asyncio(loop_scope="module")

TOKENS = {"token-alice": "alice", "token-bob": "bob"}


class BearerAuth:
    """The host's own authentication: a bearer token names the user on ``scope["state"]``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            token = headers.get(b"authorization", b"").decode().removeprefix("Bearer ")
            scope.setdefault("state", {})["user"] = TOKENS.get(token)
        await self.app(scope, receive, send)


def authenticated(request: Request) -> str | None:
    return request.state.user


def send_body(text: str, *, claimed: str | None = None) -> dict[str, object]:
    message: dict[str, object] = {
        "messageId": uuid.uuid4().hex,
        "role": "ROLE_USER",
        "parts": [{"text": text}],
    }
    if claimed is not None:
        message["metadata"] = {"participant_id": claimed}
    return {"message": message, "configuration": {"returnImmediately": True}}


def host(harness: Harness) -> httpx.AsyncClient:
    app = Starlette(
        routes=[Mount("/agents/r", app=harness.asgi_app())], middleware=[Middleware(BearerAuth)]
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://h",
        headers={"A2A-Version": "1.0"},
    )


async def test_with_a_resolver_a_spoofed_participant_header_is_ignored(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: With a resolver a spoofed participant header is ignored
        Given an agent whose resolver reads the host's authenticated user
        When alice, authenticated, sends a message with X-Participant-Id: admin
        Then the task's reporter is alice, not admin
        And bob, authenticated, cannot read alice's task, whatever header he sends
        And an unauthenticated request naming itself in the message metadata is refused
    """
    harness = Harness(
        agent_settings(tmp_path, f"r-{uuid.uuid4().hex[:6]}", "http://h/agents/r"),
        client=env.client,
        participant=authenticated,
        llm=FakeLLM([scripted("Hello alice.")]),
    )
    async with harness, host(harness) as http:
        created = await http.post(
            "/agents/r/message:send",
            json=send_body("hi"),
            headers={"Authorization": "Bearer token-alice", "X-Participant-Id": "admin"},
        )
        assert created.status_code == 200, created.text
        task_id = created.json()["task"]["id"]
        task = await harness.client.get_workflow_handle(task_id).query("task", result_type=Task)
        reporters = [p.id for p in HarnessTask(task).ext.participants if p.role is Role.REPORTER]
        assert reporters == ["alice"]

        as_bob = await http.get(
            f"/agents/r/tasks/{task_id}",
            headers={"Authorization": "Bearer token-bob", "X-Participant-Id": "alice"},
        )
        assert as_bob.status_code == 404
        as_alice = await http.get(
            f"/agents/r/tasks/{task_id}", headers={"Authorization": "Bearer token-alice"}
        )
        assert as_alice.status_code == 200

        anonymous = await http.post(
            "/agents/r/message:send",
            json=send_body("hi", claimed="alice"),
            headers={"X-Participant-Id": "alice"},
        )
        assert anonymous.status_code == 400, anonymous.text
        assert "no participant asserted" in anonymous.text
