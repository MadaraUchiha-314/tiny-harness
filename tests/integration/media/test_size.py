"""Feature: A full-size image travels from the client to the store and back
Requirement: docs/specs/issue-38/requirements.md#R1

With ``[media]`` the server's request limit admits a whole message of media (the
effective request cap), so an image at ``max_file_bytes`` (20 MiB), sent base64 in a
JSON-RPC request over a real socket, passes the limits middleware, media intake and the
store, and the media route serves it back unchanged. A body over the effective cap is
still refused with 413 before it is read, and nothing is stored (testing plan T7).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest, Task, TaskState
from starlette.applications import Starlette
from starlette.routing import Mount
from temporalio.testing import WorkflowEnvironment

from tests.fixtures import media as fx
from tests.integration.mount.conftest import agent_settings, env, free_port, serving
from tiny_harness.config import MediaConfig
from tiny_harness.harness.models import FakeLLM, scripted
from tiny_harness.service import Harness

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

ALICE = {"X-Participant-Id": "alice"}


def stored(media_dir: Path) -> list[Path]:
    """The stored objects' bytes files (not their refs or bookkeeping)."""
    extra = (".json", ".gen", ".state", ".lock", ".tmp")
    return [p for p in media_dir.rglob("*") if p.is_file() and not p.name.endswith(extra)]


async def test_a_20_mib_image_goes_through_intake_store_and_route(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: A full-size image travels from the client to the store and back
    Scenario: a 20 MiB image is accepted, stored and served; a larger body gets 413
        Given an agent with [media] at its default limits, served by uvicorn on loopback
        When alice sends a question with a PNG of max_file_bytes over JSON-RPC
        Then the request is not refused by the size limit and the turn runs to its reply
        And the store holds the image's exact bytes, which the media route serves to alice
        When a client posts a body one byte over the effective request cap
        Then it is answered 413 and nothing more is stored
    """
    media = MediaConfig()
    raw = fx.png(4, 4)
    raw = fx.png(4, 4, padding=media.max_file_bytes - len(raw) - 12)
    assert len(raw) == media.max_file_bytes

    port, agent_id = free_port(), f"s-{uuid.uuid4().hex[:6]}"
    media_dir = tmp_path / "media"
    settings = agent_settings(
        tmp_path,
        agent_id,
        f"http://127.0.0.1:{port}/agents/s",
        extra=f'[media]\ndir = "{media_dir}"\n',
    )
    assert settings.media is not None
    assert settings.media.max_file_bytes == media.max_file_bytes  # the defaults
    cap = media.request_cap(settings.server.max_request_bytes)
    harness = Harness(
        settings,
        client=env.client,
        llm=FakeLLM([scripted("A tiny image.")]),
    )
    app = Starlette(routes=[Mount("/agents/s", app=harness.asgi_app())], lifespan=harness.lifespan)
    message = Message(
        message_id=uuid.uuid4().hex,
        context_id=uuid.uuid4().hex,
        role=Role.ROLE_USER,
        parts=[
            Part(text="what is in this photo?"),
            Part(raw=raw, media_type="image/png", filename="big.png"),
        ],
    )
    message.metadata.update({"participant_id": "alice"})
    async with serving(app, port) as origin:
        url = origin + "/agents/s"
        last = Task()
        async with httpx.AsyncClient(timeout=120, headers=ALICE) as http:
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

        assert last.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
        [blob] = stored(media_dir)
        assert blob.parent.name == last.id
        assert blob.read_bytes() == raw
        media_id = blob.name.split(".")[0]
        async with httpx.AsyncClient(timeout=120, headers=ALICE) as http:
            served = await http.get(f"{url}/media/{last.id}/{media_id}")
            over = await http.post(
                f"{url}/",
                content=b"{" + b" " * cap + b"}",
                headers={"Content-Type": "application/json"},
            )
    assert (served.status_code, len(served.content)) == (200, len(raw))
    assert served.content == raw
    assert over.status_code == 413
    assert len(stored(media_dir)) == 1
