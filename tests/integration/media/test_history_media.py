"""Feature: Media in the conversation history
Requirement: docs/specs/issue-38/requirements.md#R6

A message's media enters the task's history as references to the media store, never as
bytes. The task's event log echoes the message with its media URLs, so every surface of
the task shows it and any participant fetches it through the media route.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from a2a.types import AgentCard, Part, Task
from pydantic import HttpUrl
from temporalio.testing import WorkflowEnvironment

from tests.fixtures import media as fx
from tests.integration.durable.conftest import awaiting_next_message, close, env, send, start
from tests.integration.media.flows import (
    BASE_URL,
    artifacts,
    ids,
    media_harness,
    media_task,
    parts_of,
    with_files,
)
from tests.integration.streaming_asgi import StreamingASGITransport
from tiny_harness.config import ServerConfig
from tiny_harness.harness.models import MessageItem, scripted
from tiny_harness.service.a2a import create_app
from tiny_harness.service.a2a.app import DeferredRequestHandler
from tiny_harness.service.a2a.media_routes import MediaSource
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]


async def test_media_sent_from_one_surface_is_fetched_by_another_participant(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Media in the conversation history
    Requirement: docs/specs/issue-38/requirements.md#R6

    Scenario: media sent from one surface is fetched by another participant on the task
        Given a task whose participants are alice and bob, on an agent with a media store
        When alice sends a question with an image, stored and rewritten by media intake
        And the message also carries a url part that points at another task's media
        Then the model's history holds the message with a reference to the image only
        And the task's event log echoes alice's message with the image's url part
        And bob, from another surface, fetches the image's bytes by that url
        And carol, who is not on the task, gets 404
    """
    raw = fx.png(4, 4)
    h, store = await media_harness(tmp_path, [scripted("A cat.")])
    tq, tid = ids()
    msg = await with_files(
        store, tid, "what is this?", [(raw, "image/png", "photo.png")], message_id="m1"
    )
    other = await store.put("t-other", fx.png(2, 2), media_type="image/png", name="x.png")
    msg.parts.append(
        Part(url=f"{BASE_URL}/media/t-other/{other.id}", media_type="image/png", filename="x.png")
    )
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(media_task(tid, participants=("alice", "bob"))), msg
        )
        await awaiting_next_message(handle)
        page = await handle.query(TaskWorkflow.events_since, 0)
        snapshot = await handle.query(TaskWorkflow.task_query)

        [request] = h.llm.requests
        [item] = [i for i in request.input if isinstance(i, MessageItem) and i.media]
        assert item.text == "[alice] what is this?"
        assert [a.ref.name for a in item.media] == ["photo.png"]
        assert item.media[0].ref.task_id == tid

        [echo] = artifacts(page.events, "message:")
        parts = parts_of(echo)
        assert [p.get("text") for p in parts if "text" in p] == ["what is this?"]
        urls = [str(p["url"]) for p in parts if "url" in p]
        assert urls == [f"{BASE_URL}/media/{tid}/{item.media[0].ref.id}"]
        assert echo["metadata"] == {"role": "user", "participant_id": "alice", "message_id": "m1"}

        async def lookup(task_id: str) -> Task | None:
            return snapshot if task_id == tid else None

        app = create_app(
            DeferredRequestHandler(),
            AgentCard(),
            config=ServerConfig(base_url=HttpUrl(BASE_URL)),
            media=MediaSource(store=store, lookup=lookup),
        )
        async with httpx.AsyncClient(
            transport=StreamingASGITransport(app), base_url=BASE_URL
        ) as http:
            bob = await http.get(urls[0], headers={"X-Participant-Id": "bob"})
            carol = await http.get(urls[0], headers={"X-Participant-Id": "carol"})
        assert (bob.status_code, bob.content) == (200, raw)
        assert carol.status_code == 404
        await close(handle)
