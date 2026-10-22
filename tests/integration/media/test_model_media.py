"""Feature: Media reaches the model
Requirement: docs/specs/issue-38/requirements.md#R1

The ``invoke_llm`` activity resolves each image reference to its bytes just before the
model call, so the bytes never enter workflow history; a model that takes no image input
gets a text note instead, and the user is told once in the reply's status.
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
    send,
    start,
    until,
)
from tests.integration.media.flows import (
    ids,
    media_harness,
    media_task,
    replied,
    status_texts,
    with_files,
)
from tiny_harness.harness.core import SubState
from tiny_harness.harness.models import MessageItem, scripted
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

NOT_SHOWN = "[image photo.png not shown: the model takes no image input]"


async def test_an_image_and_a_question_reach_the_model(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Media reaches the model
    Requirement: docs/specs/issue-38/requirements.md#R1

    Scenario: an image and a question reach the model
        Given an agent whose model takes image input
        When alice sends "what is in this photo?" with photo.png
        Then the model gets the question and the image's bytes in one message
        And a later turn still gives the model the earlier image (R6.1)
        And the image's bytes appear nowhere in the workflow's history
    """
    raw = fx.png(5, 5, padding=64)
    h, store = await media_harness(tmp_path, [scripted("A cat."), scripted("Grey.")])
    tq, tid = ids()
    msg = await with_files(
        store, tid, "what is in this photo?", [(raw, "image/png", "photo.png")], message_id="m1"
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        await awaiting_next_message(handle)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("what colour?", task_id=tid, message_id="m2")
        )
        await until(handle, replied("Grey."))
        first, second = h.llm.requests
        for request in (first, second):
            [item] = [i for i in request.input if isinstance(i, MessageItem) and i.media]
            assert item.text == "[alice] what is in this photo?"
            [attachment] = item.media
            assert attachment.data == raw
        history = await handle.fetch_history()
        assert base64.b64encode(raw).decode() not in history.to_json()
        await close(handle)


async def test_a_model_without_image_input_gets_a_note_and_the_task_continues(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Media reaches the model
    Requirement: docs/specs/issue-38/requirements.md#R1.7

    Scenario: a model without image input gets a note and the task continues
        Given an agent whose model takes text only
        When alice sends a question with photo.png, and later another message
        Then the model gets the question with a note that the image was not shown
        And the task's status tells the user once that the image was not given to the model
        And the task answers and waits for the next message, it does not fail
    """
    h, store = await media_harness(
        tmp_path, [scripted("I cannot see it."), scripted("Ok.")], modalities=frozenset({"text"})
    )
    tq, tid = ids()
    msg = await with_files(
        store, tid, "what is this?", [(fx.png(4, 4), "image/png", "photo.png")], message_id="m1"
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        current = await awaiting_next_message(handle)
        assert current.sub_state is SubState.AWAITING_NEXT_MESSAGE
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("never mind", task_id=tid, message_id="m2")
        )
        await until(handle, replied("Ok."))
        for request in h.llm.requests:
            [item] = [i for i in request.input if isinstance(i, MessageItem) and "photo" in i.text]
            assert item.media == ()
            assert item.text == f"[alice] what is this?\n{NOT_SHOWN}"
        page = await handle.query(TaskWorkflow.events_since, 0)
        notes = [t for t in status_texts(page.events) if "not given to the model" in t]
        assert notes == [
            "image photo.png was not given to the model: the model takes no image input"
        ]
        await close(handle)
