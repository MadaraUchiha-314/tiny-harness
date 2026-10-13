"""Fixtures for agents mounted on a host app (issue-36): per-agent settings, a real uvicorn
server on an ephemeral loopback port (agents reach each other and push to each other over a
real socket; ``httpx.ASGITransport`` buffers server-sent events), and an A2A client."""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import httpx
import uvicorn
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest, Task, TaskState
from starlette.types import ASGIApp

from tests.integration.durable.conftest import env
from tiny_harness.config import Settings
from tiny_harness.harness.security import Redactor
from tiny_harness.service.o11y import JsonFormatter

ENV = {"OPENAI_API_KEY": "sk-test-not-used"}


def agent_settings(
    tmp_path: Path,
    agent_id: str,
    base_url: str,
    *,
    agents: str = "",
    temporal: str = "",
    openai_key: str = ENV["OPENAI_API_KEY"],
) -> Settings:
    """An agent's settings: embedded mode (the tests pass the dev server's client), its own
    store, a slow heartbeat, and ``agents`` as ``[[agents]]`` tables."""
    path = tmp_path / f"{agent_id}.toml"
    path.write_text(
        f"""
[agent]
id = "{agent_id}"
name = "Agent {agent_id}"

[temporal]
mode = "embedded"
{temporal}

[openai]
model = "fake-1"

[server]
base_url = "{base_url}"
bridge_interval = "PT0.05S"

[heartbeat]
interval = "PT1H"

[store]
sqlite_path = "{tmp_path / agent_id}.sqlite3"

{agents}
"""
    )
    return Settings.load(path, env={**ENV, "OPENAI_API_KEY": openai_key})


@contextmanager
def captured_json_logs(redactor: Redactor | None = None) -> Generator[io.StringIO]:
    """The harness's JSON log lines, in a handler of this test's own: ``configure_logging``
    keeps the first stream it was given, so a test cannot rely on it to capture."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(redactor))
    logger = logging.getLogger("tiny_harness")
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@asynccontextmanager
async def serving(app: ASGIApp, port: int) -> AsyncGenerator[str]:
    """``app`` on ``127.0.0.1:port`` with its lifespan; yields the origin."""
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if task.done():
                task.result()
                raise RuntimeError("the server stopped before it started")
            await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait([task])


async def ask(url: str, text: str, *, user: str = "alice", task_id: str = "") -> Task:
    """Send ``text`` to the agent at ``url`` and return the task as of its last event."""
    message = Message(
        message_id=uuid.uuid4().hex,
        context_id=uuid.uuid4().hex,
        role=Role.ROLE_USER,
        parts=[Part(text=text)],
    )
    if task_id:
        message.task_id = task_id
    message.metadata.update({"participant_id": user})
    last = Task()
    async with httpx.AsyncClient(timeout=60, headers={"X-Participant-Id": user}) as http:
        client = await create_client(
            url, client_config=ClientConfig(httpx_client=http, streaming=True)
        )
        async for event in client.send_message(SendMessageRequest(message=message)):
            if event.HasField("task"):
                last.CopyFrom(event.task)
            elif event.HasField("status_update"):
                last.id = event.status_update.task_id
                last.status.CopyFrom(event.status_update.status)
        await client.close()
    return last


def state(task: Task) -> str:
    return TaskState.Name(task.status.state)


def reply_text(task: Task) -> str:
    return "\n".join(p.text for p in task.status.message.parts if p.text)


__all__ = [
    "ENV",
    "agent_settings",
    "ask",
    "captured_json_logs",
    "env",
    "free_port",
    "reply_text",
    "serving",
    "state",
]
