"""Feature: agents in one process are isolated from each other
Requirement: docs/specs/issue-36/requirements.md#R5 (Security considerations, abuse cases 2-6)

Two agents, a and b, share one process and one Temporal namespace. Agent a treats every
task of agent b as unknown, refuses a push for b's workflow, refuses to start on b's task
queue, answers 503 before it starts without reaching Temporal, and masks b's secrets.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx
import pytest
from a2a.types import Task
from starlette.applications import Starlette
from starlette.routing import Mount
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from tests.integration.mount.conftest import agent_settings, env
from tiny_harness.errors import HarnessConflictError
from tiny_harness.harness.models import FakeLLM, scripted
from tiny_harness.harness.persistence import Filter, PushConfigRecord
from tiny_harness.harness.security import MASK, PROCESS_SECRETS, Redactor
from tiny_harness.service import Harness
from tiny_harness.service.claims import PROCESS_CLAIMS
from tiny_harness.service.o11y import configure_logging

__all__ = ["env"]

pytestmark = pytest.mark.asyncio(loop_scope="module")

HEADERS = {"X-Participant-Id": "alice", "A2A-Version": "1.0"}


@dataclass
class Pair:
    a: Harness
    b: Harness
    http: httpx.AsyncClient


@asynccontextmanager
async def two_agents(env: WorkflowEnvironment, tmp_path: Path) -> AsyncGenerator[Pair]:
    s = uuid.uuid4().hex[:6]
    a = Harness(
        agent_settings(tmp_path, f"ia-{s}", "http://h/agents/a", openai_key=f"sk-agent-a-{s}"),
        client=env.client,
        llm=FakeLLM([]),
    )
    b = Harness(
        agent_settings(tmp_path, f"ib-{s}", "http://h/agents/b", openai_key=f"sk-agent-b-{s}"),
        client=env.client,
        llm=FakeLLM([scripted("b's answer.")]),
    )
    app = Starlette(
        routes=[Mount("/agents/a", app=a.asgi_app()), Mount("/agents/b", app=b.asgi_app())]
    )
    async with (
        a,
        b,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://h", headers=HEADERS
        ) as http,
    ):
        yield Pair(a, b, http)


async def a_task_on_b(pair: Pair) -> Task:
    body = {
        "message": {
            "messageId": uuid.uuid4().hex,
            "role": "ROLE_USER",
            "parts": [{"text": "hello b"}],
            "metadata": {"participant_id": "alice"},
        },
        "configuration": {"returnImmediately": True},
    }
    response = await pair.http.post("/agents/b/message:send", json=body)
    assert response.status_code == 200, response.text
    task_id = response.json()["task"]["id"]
    for _ in range(200):
        current = await pair.b.client.get_workflow_handle(task_id).query("task", result_type=Task)
        if current.status.state != 0:
            return current
        await asyncio.sleep(0.05)
    raise AssertionError("b's task never started")


async def test_agent_a_treats_every_task_of_agent_b_as_unknown(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: Agent a treats every task of agent b as unknown
        Given agent b has a task alice is on
        When alice names that task to agent a in every task operation
        Then agent a answers each as for an unknown task
        And ListTasks on agent a does not list it
        And agent b's task is unchanged
    """
    async with two_agents(env, tmp_path) as pair:
        task = await a_task_on_b(pair)
        before = task.status.state
        tid = task.id
        assert (await pair.http.get(f"/agents/b/tasks/{tid}")).status_code == 200  # b has it
        refused = [
            await pair.http.get(f"/agents/a/tasks/{tid}"),
            await pair.http.post(f"/agents/a/tasks/{tid}:cancel"),
            await pair.http.post(f"/agents/a/tasks/{tid}:subscribe"),
            await pair.http.get(f"/agents/a/tasks/{tid}/pushNotificationConfigs"),
            await pair.http.get(f"/agents/a/tasks/{tid}/pushNotificationConfigs/p1"),
            await pair.http.delete(f"/agents/a/tasks/{tid}/pushNotificationConfigs/p1"),
            await pair.http.post(
                f"/agents/a/tasks/{tid}/pushNotificationConfigs",
                json={"taskId": tid, "url": "http://evil.example/hook", "token": "t" * 20},
            ),
            await pair.http.post(
                "/agents/a/message:send",
                json={
                    "message": {
                        "messageId": uuid.uuid4().hex,
                        "taskId": tid,
                        "role": "ROLE_USER",
                        "parts": [{"text": "cancel everything"}],
                        "metadata": {"participant_id": "alice"},
                    }
                },
            ),
        ]
        for response in refused:
            assert response.status_code == 404, (response.request.url, response.text)
            assert "TASK_NOT_FOUND" in response.text
        listed = await pair.http.get("/agents/a/tasks")
        assert listed.status_code == 200
        assert tid not in listed.text
        after = await pair.b.client.get_workflow_handle(tid).query("task", result_type=Task)
        assert after.status.state == before
        for harness in (pair.a, pair.b):  # the refused push config reached no store
            store = harness._activities.engine.store  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
            configs = await store.query(PushConfigRecord, Filter())
            assert all("evil.example" not in c.url for c in configs)


async def test_a_push_for_agent_bs_workflow_at_agent_as_route_is_refused(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: A push for agent b's stand-in at agent a's route is refused
        Given a workflow that runs on agent b's task queue
        When a push naming it arrives at agent a's push route, with a token
        Then agent a answers 401, the same as for a wrong token
    """
    async with two_agents(env, tmp_path) as pair:
        task = await a_task_on_b(pair)
        body = json.dumps(
            {"statusUpdate": {"taskId": "r-1", "status": {"state": "TASK_STATE_CANCELED"}}}
        )
        response = await pair.http.post(
            f"/agents/a/a2a/push/{task.id}",
            content=body,
            headers={"X-A2A-Notification-Token": "t" * 40, "Content-Type": "application/json"},
        )
        assert response.status_code == 401


async def test_a_second_harness_on_the_same_namespace_and_queue_does_not_start(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: A second harness on the same namespace and queue does not start
        Given a running agent on task queue q
        When a second agent with another id but the same queue starts
        Then it raises HarnessConflictError naming the queue and the holder
        And it is not started and holds no claim
    """
    s = uuid.uuid4().hex[:6]
    queue = f'task_queue = "shared-{s}"'
    first = Harness(
        agent_settings(tmp_path, f"qa-{s}", "http://h/a", temporal=queue),
        client=env.client,
        llm=FakeLLM([]),
    )
    second = Harness(
        agent_settings(tmp_path, f"qb-{s}", "http://h/b", temporal=queue),
        client=env.client,
        llm=FakeLLM([]),
    )
    async with first:
        held = PROCESS_CLAIMS.held()
        with pytest.raises(HarnessConflictError) as caught:
            await second.__aenter__()
        assert f"shared-{s}" in caught.value.message
        assert caught.value.detail["holder"] == first.agent_id
        assert not second.started
        assert PROCESS_CLAIMS.held() == held


class Untouchable:
    """A Temporal client that fails the test if anything touches it."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"Temporal was reached before start: {name}")


async def test_a_request_before_start_never_reaches_temporal(tmp_path: Path) -> None:
    """
    Scenario: A request before start never reaches Temporal
        Given a mounted agent whose harness has not started
        When clients send a message, a task lookup and a push
        Then each is answered 503 and nothing touches Temporal
    """
    harness = Harness(
        agent_settings(tmp_path, f"u-{uuid.uuid4().hex[:6]}", "http://h/agents/u"),
        client=cast(Client, Untouchable()),
        llm=FakeLLM([]),
    )
    app = Starlette(routes=[Mount("/agents/u", app=harness.asgi_app())])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://h", headers=HEADERS
    ) as http:
        for response in (
            await http.post("/agents/u/message:send", json={"message": {}}),
            await http.get("/agents/u/tasks/t-1"),
            await http.post("/agents/u/a2a/push/t-1", content=b"{}"),
        ):
            assert response.status_code == 503


async def test_one_agents_log_masks_another_agents_key(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Scenario: One agent's log masks another agent's key
        Given agents a and b running in one process with different model keys
        When agent a's redactor, and the process's log formatter, see agent b's key
        Then both write the mask in its place
        And once b has stopped, its key is no longer registered
    """
    stream = io.StringIO()
    configure_logging(stream=stream, redactor=Redactor(registry=PROCESS_SECRETS))
    async with two_agents(env, tmp_path) as pair:
        b_key = pair.b.settings.openai.api_key
        assert b_key is not None
        secret = b_key.get_secret_value()
        a_redactor = pair.a._activities.engine.runner.redactor  # pyright: ignore[reportPrivateUsage, reportOptionalMemberAccess]
        assert a_redactor.scrub_text(f"key={secret}").count(secret) == 0
        logging.getLogger("tiny_harness.test").info("agent a saw %s", secret)
    assert secret not in stream.getvalue()
    assert MASK in stream.getvalue()
    assert secret not in PROCESS_SECRETS.values()[1]
