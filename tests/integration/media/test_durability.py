"""Feature: Media survives a worker restart
Requirement: docs/specs/issue-38/requirements.md#R6.4

The workflow history holds media references only and the bytes live in the media store,
so a worker that restarts, on new process objects over the same store, still resolves
every earlier image; a spoken reply cut by the restart is written again by the retried
attempt as a new generation, and a reader of the old generation is told.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.fixtures import media as fx
from tests.integration.durable.conftest import (
    close,
    env,
    message,
    send,
    start,
    until,
)
from tests.integration.media.flows import (
    ids,
    media_harness,
    media_task,
    replied,
    with_files,
)
from tests.integration.media.test_speech import (
    ONE,
    TWO,
    GatedTTS,
    read_all,
    speech_of,
    spoken,
    wait_for,
)
from tiny_harness.harness.media import MediaFailed, MediaInterrupted
from tiny_harness.harness.models import FakeTextToSpeech, MessageItem, scripted
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]


async def test_media_survives_a_worker_restart(env: WorkflowEnvironment, tmp_path: Path) -> None:
    """
    Feature: Media survives a worker restart
    Requirement: docs/specs/issue-38/requirements.md#R6.4

    Scenario: media survives a worker restart
        Given alice sent photo.png with speak=true and the reply is being spoken
        And a reader has the speech's first chunk
        When the worker stops mid-speech and a new worker starts over the same media store
        Then the retried speech attempt writes a new generation, in full
        And the reader of the first generation is told its stream ended early
        And when alice asks again, the new worker gives the model the photo's bytes
    """
    image = fx.png(5, 5)
    gated = GatedTTS()
    first, store = await media_harness(tmp_path, [scripted("A cat.")], tts=gated)
    first.heartbeat_every = 0.5  # alive until it stops
    tq, tid = ids()
    msg = await with_files(
        store,
        tid,
        "what is this?",
        [(image, "image/png", "photo.png")],
        message_id="m1",
        speak=True,
    )
    begin = start(media_task(tid), heartbeat_timeout=timedelta(seconds=3))
    async with first.worker(env.client, tq, sticky=False):
        handle = await send(env.client, tq, begin, msg)
        await until(handle, replied("A cat."))
        page = await handle.query(TaskWorkflow.events_since, 0)
        [media_id] = speech_of(page.events)
        await wait_for(lambda: len(gated.calls) == 1)
        ref = await store.lookup(tid, media_id)
        assert ref is not None
        reader = store.read_stream(ref, poll=0.01, idle_timeout=10)
        assert await asyncio.wait_for(anext(reader), timeout=5) == ONE

    second, store = await media_harness(
        tmp_path, [scripted("Still a cat.")], tts=FakeTextToSpeech([TWO, TWO, TWO])
    )
    async with second.worker(env.client, tq, sticky=False):
        with pytest.raises((MediaInterrupted, MediaFailed)):
            async for _ in reader:
                pass
        done = await spoken(store, tid, media_id)
        assert await read_all(store, done) == TWO * 3
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("and now?", task_id=tid, message_id="m2")
        )
        await until(handle, replied("Still a cat."))
        [request] = second.llm.requests
        [item] = [i for i in request.input if isinstance(i, MessageItem) and i.media]
        [attachment] = item.media
        assert attachment.ref.name == "photo.png" and attachment.data == image
        await close(handle)
