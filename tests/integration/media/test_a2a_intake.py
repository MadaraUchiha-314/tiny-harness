"""Feature: Media intake at the A2A server
Requirement: docs/specs/issue-38/requirements.md#R1

A new turn's file parts are checked, stored and rewritten before the message enters the
workflow. A refused attachment answers the request with InvalidParams carrying the reason
and the limit; no task is started and nothing is stored.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

import pytest
from a2a.types import GetTaskRequest, Message, Part, SendMessageRequest, TaskState
from a2a.types import Role as A2ARole
from a2a.utils.errors import A2AError, InvalidParamsError
from temporalio.testing import WorkflowEnvironment

from tests.fixtures import media as fx
from tests.integration.a2a.conftest import make_server
from tests.integration.durable.conftest import env
from tiny_harness.config import MediaConfig
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore, MediaIntake
from tiny_harness.harness.models import scripted

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]


def with_image(raw: bytes, *, context_id: str) -> Message:
    msg = Message(
        message_id=uuid.uuid4().hex,
        context_id=context_id,
        role=A2ARole.ROLE_USER,
        parts=[
            Part(text="what is in this photo?"),
            Part(raw=raw, media_type="image/png", filename="photo.png"),
        ],
    )
    msg.metadata.update({"participant_id": "alice"})
    return msg


def intake(root: Path, *, max_file_bytes: int = MediaConfig().max_file_bytes) -> MediaIntake:
    store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), root)
    config = MediaConfig(max_file_bytes=max_file_bytes)
    return MediaIntake(store, config, base_url="http://harness")


def data(error: A2AError) -> dict[str, object]:
    """The error's data: the refusal's reason, limit and part index."""
    return cast(dict[str, object], getattr(error, "data", None) or {})


def stored(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix == ".json"]


async def test_a_file_without_media_is_refused_as_invalid_params(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Media intake at the A2A server
    Scenario: a file sent to an agent without [media] is refused
        Given an agent with no [media] section
        When a participant sends a message with an image
        Then the request fails with InvalidParams, reason media_off
        And no task is started and the model is not called
    """
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(env, [scripted("Hi.")], task_queue=f"tq-{suffix}")
    async with server:
        with pytest.raises(InvalidParamsError) as caught:
            async for _ in server.a2a().send_message(
                SendMessageRequest(message=with_image(fx.png(4, 4), context_id=f"c-{suffix}"))
            ):
                pass
    assert data(caught.value) == {"reason": "media_off"}
    assert server.harness.llm.requests == []


async def test_an_oversized_file_is_refused_and_nothing_is_stored(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Media intake at the A2A server
    Scenario: an oversized file is refused with its limit
        Given an agent whose [media] max_file_bytes is 64
        When a participant sends a larger image
        Then the request fails with InvalidParams naming reason too_large and limit 64
        And nothing is stored and the model is not called
    """
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(
        env,
        [scripted("Hi.")],
        task_queue=f"tq-{suffix}",
        media_intake=intake(tmp_path, max_file_bytes=64),
    )
    async with server:
        with pytest.raises(InvalidParamsError) as caught:
            async for _ in server.a2a().send_message(
                SendMessageRequest(
                    message=with_image(fx.png(4, 4, padding=200), context_id=f"c-{suffix}")
                )
            ):
                pass
    assert data(caught.value)["reason"] == "too_large"
    assert data(caught.value)["limit"] == "64"
    assert stored(tmp_path) == []
    assert server.harness.llm.requests == []


async def test_an_image_is_stored_before_the_turn_starts(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Media intake at the A2A server
    Scenario: an accepted image is stored and the turn runs
        Given an agent with [media]
        When a participant sends a message with an image
        Then the image is stored under the task and the turn runs to its reply
    """
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(
        env, [scripted("A cat.")], task_queue=f"tq-{suffix}", media_intake=intake(tmp_path)
    )
    async with server:
        task_id = ""
        async for event in server.a2a().send_message(
            SendMessageRequest(message=with_image(fx.png(4, 4), context_id=f"c-{suffix}"))
        ):
            if event.HasField("task"):
                task_id = event.task.id
        assert task_id
        task = await server.a2a().get_task(GetTaskRequest(id=task_id))
    assert task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    [meta] = stored(tmp_path)
    assert meta.parent.name == task_id


async def test_a_url_file_part_is_refused(env: WorkflowEnvironment, tmp_path: Path) -> None:
    """
    Feature: Media intake at the A2A server
    Scenario: a file part by URL is refused, never fetched
        Given an agent with [media]
        When a participant sends a file part that is a URL
        Then the request fails with InvalidParams, reason url_not_accepted
    """
    suffix = uuid.uuid4().hex[:8]
    server = await make_server(
        env, [scripted("Hi.")], task_queue=f"tq-{suffix}", media_intake=intake(tmp_path)
    )
    message = with_image(fx.png(4, 4), context_id=f"c-{suffix}")
    message.parts[1].url = "http://169.254.169.254/latest/meta-data"
    async with server:
        with pytest.raises(A2AError) as caught:
            async for _ in server.a2a().send_message(SendMessageRequest(message=message)):
                pass
    assert isinstance(caught.value, InvalidParamsError)
    assert data(caught.value) == {"reason": "url_not_accepted", "part": "1"}
