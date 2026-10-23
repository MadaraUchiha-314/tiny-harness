"""Feature: Images from the agent
Requirement: docs/specs/issue-38/requirements.md#R2

The ``generate_image`` intrinsic, registered only where an image generator exists, calls
the generator inside the tool activity, stores the image and answers the model with a
reference. The workflow shows it as the ``image:<mediaId>`` artifact, named by its alt
text, and adds an agent note that carries the image, so later turns can see it (R2.5).
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from temporalio.testing import WorkflowEnvironment

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
    BASE_URL,
    artifacts,
    ids,
    media_harness,
    media_task,
    parts_of,
    replied,
)
from tiny_harness.harness.models import (
    FakeImageGenerator,
    MessageItem,
    ToolResultItem,
    scripted,
)
from tiny_harness.harness.models.images import blank_png
from tiny_harness.harness.tools import ToolCall
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

ALT = "A green sofa in a bright room"


def draw(call_id: str = "c1") -> ToolCall:
    return ToolCall(
        call_id=call_id,
        name="generate_image",
        arguments={"prompt": "a green sofa", "size": "1024x1536", "alt": ALT},
    )


async def test_generate_image_shows_an_image_and_a_later_turn_sees_it(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Images from the agent
    Requirement: docs/specs/issue-38/requirements.md#R2

    Scenario: generate_image shows an image and a later turn sees it
        Given an agent with an image generator
        When alice asks for a picture and the model calls generate_image
        Then the generator is called with the prompt and the size
        And the image is stored and shown as the "image:<id>" artifact named by its alt text
        And the model reads "image <id> shown to the user" as the tool's result
        And the next model call, and a later turn's, get the image as an agent note
        And the image's bytes appear nowhere in the workflow's history
    """
    images = FakeImageGenerator()
    h, store = await media_harness(
        tmp_path,
        [scripted(tool_calls=[draw()]), scripted("Here it is."), scripted("It is green.")],
        images=images,
    )
    tq, tid = ids()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(media_task(tid)),
            message("draw me a green sofa", task_id=tid, message_id="m1"),
        )
        await awaiting_next_message(handle)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("what colour is it?", task_id=tid, message_id="m2")
        )
        await until(handle, replied("It is green."))

        [call] = images.calls
        assert (call.prompt, call.size) == ("a green sofa", "1024x1536")
        page = await handle.query(TaskWorkflow.events_since, 0)
        [artifact] = artifacts(page.events, "image:")
        media_id = str(artifact["artifactId"]).removeprefix("image:")
        assert artifact["name"] == ALT
        [part] = parts_of(artifact)
        assert part["url"] == f"{BASE_URL}/media/{tid}/{media_id}"
        assert part["mediaType"] == "image/png"
        ref = await store.lookup(tid, media_id)
        assert ref is not None and (ref.width, ref.height) == (1024, 1536)
        raw = await store.get(ref)
        assert raw == blank_png(1024, 1536)

        _, after_tool, later = h.llm.requests
        [result] = [i for i in after_tool.input if isinstance(i, ToolResultItem)]
        assert f"image {media_id} shown to the user" in str(result.result.content[0].text)
        for request in (after_tool, later):
            [note] = [i for i in request.input if isinstance(i, MessageItem) and i.media]
            assert note.source == "agent"
            assert f"[image generated: {ALT}]" in note.text
            [attachment] = note.media
            assert attachment.ref.id == media_id and attachment.data == raw
        history = await handle.fetch_history()
        assert base64.b64encode(raw).decode() not in history.to_json()
        await close(handle)


async def test_no_generate_image_tool_without_an_image_generator(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Images from the agent
    Requirement: docs/specs/issue-38/requirements.md#R5.5

    Scenario: an instance without image generation offers no generate_image tool
        Given an agent with a media store and no image generator
        When alice sends a message
        Then the model's tools do not include generate_image
    """
    h, _ = await media_harness(tmp_path, [scripted("Hello.")])
    tq, tid = ids()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(media_task(tid)), message("hi", task_id=tid, message_id="m1")
        )
        await awaiting_next_message(handle)
        [request] = h.llm.requests
        assert "generate_image" not in {t.name for t in request.tools}
        await close(handle)
