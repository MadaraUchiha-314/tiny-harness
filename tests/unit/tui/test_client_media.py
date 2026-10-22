"""T1 (issue-38 R1.3, R4.1, design critic 8): the TUI client builds raw file parts, says
``speak`` and a recording's ``voice``, reads the card's media params, and fetches media
only from the agent's own origin."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from a2a.client.client import Client as A2AClient
from a2a.types import AgentCapabilities, AgentCard, AgentExtension
from google.protobuf import json_format

from tiny_harness.harness.media.extension import MEDIA_EXT_URI, MediaExtensionParams
from tiny_harness.interaction.tui.client import (
    Attachment,
    SdkClient,
    card_media,
    same_origin,
    user_message,
)


def test_user_message_carries_raw_files_speak_and_voice() -> None:
    photo = Attachment("sofa.png", "image/png", b"\x89PNG...", width=2, height=3)
    voice = Attachment("voice.wav", "audio/wav", b"RIFF....", duration_ms=4000, voice=True)
    message = user_message(
        "Which?", files=(photo, voice), task_id="t-1", context_id="c", participant="ana", speak=True
    )
    text, image, audio = message.parts
    assert text.text == "Which?"
    assert (image.raw, image.media_type, image.filename) == (photo.data, "image/png", "sofa.png")
    assert not image.metadata.fields
    assert json_format.MessageToDict(audio.metadata) == {"voice": True, "durationMs": 4000}
    meta = json_format.MessageToDict(message.metadata)
    assert meta == {"participant_id": "ana", "speak": True}
    plain = user_message("hi", task_id=None, context_id="c", participant=None)
    assert [p.text for p in plain.parts] == ["hi"] and "speak" not in plain.metadata.fields
    only_file = user_message("", files=(photo,), task_id=None, context_id="c", participant=None)
    assert [p.WhichOneof("content") for p in only_file.parts] == ["raw"]


def test_card_media_reads_the_extension_params() -> None:
    params = MediaExtensionParams(input=("image/png",), max_file_bytes=10)
    extension = AgentExtension(uri=MEDIA_EXT_URI)
    extension.params.update(params.model_dump(mode="json", by_alias=True))
    card = AgentCard(capabilities=AgentCapabilities(extensions=[extension]))
    assert card_media(card) == params
    assert card_media(AgentCard()) is None


def test_same_origin() -> None:
    assert same_origin("http://127.0.0.1:8080/media/t/m", "http://127.0.0.1:8080")
    assert not same_origin("http://evil.example/media/t/m", "http://127.0.0.1:8080")
    assert not same_origin("https://127.0.0.1:8080/media/t/m", "http://127.0.0.1:8080")
    assert not same_origin("http://127.0.0.1:8080/media/t/m", "")


async def test_get_media_never_asks_another_host() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"abc")

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers={"X-Participant-Id": "ana"}
    )
    client = SdkClient(
        cast_client(), http=http, participant="ana", base_url="http://127.0.0.1:8080"
    )
    got = [c async for c in client.get_media("http://127.0.0.1:8080/media/t/m")]
    assert b"".join(got) == b"abc"
    assert requests[0].headers["X-Participant-Id"] == "ana"
    with pytest.raises(httpx.InvalidURL):
        [c async for c in client.get_media("http://evil.example/media/t/m")]
    assert len(requests) == 1
    await http.aclose()


def cast_client() -> A2AClient:
    return cast(A2AClient, object())  # get_media never touches the A2A client
