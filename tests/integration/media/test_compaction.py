"""Feature: Compaction keeps the media named
Requirement: docs/specs/issue-38/requirements.md#R6.2

WHEN compaction folds turns that held media, the summarise call (inside the compact
activity) carries the images the model can take, and the summary names every folded
media item in one line, with its transcript or a description, or a fallback line.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.fixtures import media as fx
from tests.integration.durable.conftest import (
    awaiting_next_message,
    close,
    env,
    message,
    start,
    until,
)
from tests.integration.durable.conftest import send as send_message
from tests.integration.media.flows import (
    ids,
    media_harness,
    media_task,
    replied,
    with_files,
)
from tiny_harness.harness.models import FakeSpeechToText, MessageItem, scripted
from tiny_harness.harness.persistence import CompactionStoreRecord, Filter
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]


async def test_compaction_names_every_media_item(env: WorkflowEnvironment, tmp_path: Path) -> None:
    """
    Feature: Compaction keeps the media named
    Requirement: docs/specs/issue-38/requirements.md#R6.2

    Scenario: compaction names every media item
        Given an agent whose model takes images, with speech-to-text
        And alice sent photo.png and memo.wav in one message, and the turn was large
        When her next message makes the context go over budget
        Then the summarise call carries the photo's bytes
        And the summary names the photo and the memo, the memo with its transcript
        And the next turn's context holds that summary
        And the media stays in the store
        And no media bytes appear in the workflow's history
    """
    image, audio = fx.png(6, 4), fx.wav(seconds=1)
    stt = FakeSpeechToText(["buy milk"])
    h, store = await media_harness(
        tmp_path,
        [
            scripted("A cat and a memo.", input_tokens=20_000),
            scripted("Alice shared a photo and a memo."),
            scripted("Done."),
        ],
        stt=stt,
    )
    tq, tid = ids()
    files = [(image, "image/png", "photo.png"), (audio, "audio/wav", "memo.wav")]
    first = await with_files(store, tid, "look at these", files, message_id="m1")
    async with h.worker(env.client, tq):
        handle = await send_message(env.client, tq, start(media_task(tid)), first)
        await awaiting_next_message(handle)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("anything else?", task_id=tid, message_id="m2")
        )
        await until(handle, replied("Done."))

        _, summarise, later = h.llm.requests
        [item] = summarise.input
        assert isinstance(item, MessageItem)
        [carried] = item.media
        assert carried.ref.name == "photo.png" and carried.data == image
        photo = carried.ref
        [stored] = await h.store.query(CompactionStoreRecord, Filter(task_id=tid))
        record = stored.record
        memo_id = next(
            line.split(" ")[1] for line in record.summary.splitlines() if line.startswith("[audio ")
        )
        assert record.summary.splitlines() == [
            "Alice shared a photo and a memo.",
            f'[image {photo.id} "photo.png": not described]',
            f'[audio {memo_id} "memo.wav": buy milk]',
        ]
        context = later.input[0]
        assert isinstance(context, MessageItem) and record.summary in context.text
        assert await store.get(photo) == image
        history = (await handle.fetch_history()).to_json()
        assert base64.b64encode(image).decode() not in history
        assert base64.b64encode(audio).decode() not in history
        await close(handle)
