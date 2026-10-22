"""Feature: The media route streams a growing object
Requirement: docs/specs/issue-38/requirements.md#R4

``GET /media/{task}/{id}`` serves a spoken reply while it is written: each chunk reaches
the client as it is appended, the stream ends cleanly when speech is done, and it aborts
when speech fails or a newer generation starts. A replay reads the newest generation from
its start. ``httpx.ASGITransport`` buffers a response, so these tests use
``StreamingASGITransport``, which delivers each chunk as it is sent.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from a2a.types import AgentCard, Task
from fastapi import FastAPI
from pydantic import HttpUrl
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import ASGIApp
from temporalio.testing import WorkflowEnvironment

from tests.fixtures import media as fx
from tests.integration.mount.conftest import agent_settings, ask, env, free_port, serving
from tests.integration.streaming_asgi import StreamingASGITransport
from tiny_harness.config import ServerConfig
from tiny_harness.fastapi import harness_router
from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import PCM_MEDIA_TYPE, FileMediaStore, MediaRef
from tiny_harness.harness.models import FakeLLM, scripted
from tiny_harness.service import Harness
from tiny_harness.service.a2a import create_app
from tiny_harness.service.a2a.app import DeferredRequestHandler, RouteOptions, build_routes
from tiny_harness.service.a2a.media_routes import MEDIA_PATH, MediaSource

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

ALICE = {"X-Participant-Id": "alice"}
CHUNK = b"\x01\x00" * 512


def task() -> Task:
    ext = TaskExtensionData(
        name="n",
        goal="g",
        participants=(Participant(id="alice", kind="human", role=Role.REPORTER),),
    )
    return HarnessTask.new("t-1", "ctx", ext).proto


@asynccontextmanager
async def route(tmp_path: Path) -> AsyncGenerator[tuple[FileMediaStore, httpx.AsyncClient]]:
    store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), tmp_path)
    known = task()

    async def lookup(task_id: str) -> Task | None:
        return known if task_id == known.id else None

    app = create_app(
        DeferredRequestHandler(),
        AgentCard(),
        config=ServerConfig(base_url=HttpUrl("http://harness")),
        media=MediaSource(store=store, lookup=lookup, poll=0.01),
    )
    transport = StreamingASGITransport(app)
    async with httpx.AsyncClient(transport=transport, base_url="http://harness") as http:
        yield store, http


async def speech(store: FileMediaStore) -> MediaRef:
    return await store.create("t-1", "s1", media_type=PCM_MEDIA_TYPE)


async def test_a_chunk_reaches_the_client_while_speech_is_written(tmp_path: Path) -> None:
    """
    Feature: The media route streams a growing object
    Scenario: chunks arrive as they are appended, and done ends the stream cleanly
        Given an open speech object with one chunk written
        When a participant of the task requests it
        Then the first chunk arrives before the writer has finished
        And the stream ends cleanly with every byte once the writer closes
    """
    async with route(tmp_path) as (store, http):
        writer = await store.begin(await speech(store))
        await writer.append(CHUNK)
        async with http.stream("GET", "/media/t-1/s1", headers=ALICE) as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == PCM_MEDIA_TYPE
            assert response.headers["cache-control"] == "no-store"
            assert "content-length" not in response.headers
            chunks = response.aiter_bytes()
            first = await asyncio.wait_for(anext(chunks), timeout=2)
            assert first == CHUNK
            await writer.append(CHUNK)
            await writer.close()
            rest = b"".join([c async for c in chunks])
    assert first + rest == CHUNK * 2


@pytest.mark.parametrize("ending", ["failed", "new generation"])
async def test_a_failed_or_superseded_speech_aborts_the_stream(tmp_path: Path, ending: str) -> None:
    """
    Feature: The media route streams a growing object
    Scenario: speech that fails or is retried aborts the stream; replay reads the retry
        Given a client reading an open speech object
        When the writer closes it as failed, or a retry begins a new generation
        Then the client's stream breaks instead of ending cleanly
        And after a retry, requesting the URL again reads the new generation from its start
    """
    async with route(tmp_path) as (store, http):
        ref = await speech(store)
        writer = await store.begin(ref)
        await writer.append(CHUNK)
        with pytest.raises(httpx.RemoteProtocolError):
            async with http.stream("GET", "/media/t-1/s1", headers=ALICE) as response:
                chunks = response.aiter_bytes()
                assert await asyncio.wait_for(anext(chunks), timeout=2) == CHUNK
                if ending == "failed":
                    await writer.close(failed=True)
                else:
                    retry = await store.begin(ref)
                    await retry.append(b"\x02\x00" * 4)
                    await retry.close()
                async for _ in chunks:
                    pass
        if ending == "new generation":
            replay = await http.get("/media/t-1/s1", headers=ALICE)
            assert replay.content == b"\x02\x00" * 4


@pytest.mark.parametrize("host", ["starlette", "fastapi"])
async def test_a_mounted_harness_serves_its_media_to_participants_only(
    env: WorkflowEnvironment, tmp_path: Path, host: str
) -> None:
    """
    Feature: The media route
    Scenario: a mounted agent serves a task's media to its participants only
        Given an agent with [media], mounted at /agents/m in a Starlette or a FastAPI app
        And a task of alice's holding an image
        When alice requests the image under the agent's prefix
        Then she gets its bytes, and bob gets 404
    """
    port, agent_id = free_port(), f"m-{uuid.uuid4().hex[:6]}"
    media_dir = tmp_path / "media"
    harness = Harness(
        agent_settings(
            tmp_path,
            agent_id,
            f"http://127.0.0.1:{port}/agents/m",
            extra=f'[media]\ndir = "{media_dir}"\n',
        ),
        client=env.client,
        llm=FakeLLM([scripted("Hello.")]),
    )
    if host == "fastapi":
        app: ASGIApp = FastAPI()
        app.include_router(harness_router(harness))
    else:
        app = Starlette(
            routes=[Mount("/agents/m", app=harness.asgi_app())], lifespan=harness.lifespan
        )
    raw = fx.png(4, 4)
    async with serving(app, port) as origin:
        done = await ask(origin + "/agents/m", "hi")
        store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), media_dir)
        ref = await store.put(done.id, raw, media_type="image/png", name="p.png")
        url = f"{origin}/agents/m/media/{done.id}/{ref.id}"
        async with httpx.AsyncClient() as http:
            mine = await http.get(url, headers=ALICE)
            theirs = await http.get(url, headers={"X-Participant-Id": "bob"})
    assert (mine.status_code, mine.content) == (200, raw)
    assert mine.headers["x-content-type-options"] == "nosniff"
    assert theirs.status_code == 404


def test_route_options_turn_the_media_route_off() -> None:
    def paths(options: RouteOptions) -> set[str]:
        routes = build_routes(
            DeferredRequestHandler(),
            AgentCard,
            config=ServerConfig(base_url=HttpUrl("http://harness")),
            options=options,
            media=lambda: None,
        )
        return {r.path for r in routes if isinstance(r, Route)}

    assert MEDIA_PATH in paths(RouteOptions())
    assert MEDIA_PATH not in paths(RouteOptions(media=False))
