"""T1: media in the model request (issue-38 R1.6, R5.1, R5.2).

Each adapter maps every row of the design's content table: text, image, native audio and
an audio transcript. A message with no media keeps today's plain-string content, so a
text-only request body is byte-identical to 0.8.0 (the golden bodies under
``tests/fixtures/media/golden/`` were recorded from 0.8.0's adapters). An attachment the
adapter needs but whose bytes were not resolved is a programming error: ``ProviderError``.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import httpx2
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import SecretStr

from tiny_harness.errors import ProviderError
from tiny_harness.harness.media import MediaAttachment, MediaKind, MediaRef
from tiny_harness.harness.models import (
    AnthropicLLM,
    FakeLLM,
    LLMModelInfo,
    LLMRequest,
    MessageItem,
    OpenAILLM,
    Role,
    ToolCallItem,
    ToolResultItem,
)
from tiny_harness.harness.tools import ToolCall, ToolDefinition, ToolResult

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
GOLDEN = FIXTURES / "media" / "golden"
JsonObject = dict[str, object]
Capture = Callable[[LLMRequest], Awaitable[bytes]]

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
WAV = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 16
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 16


def _respond(body: bytes) -> tuple[list[httpx2.Request], httpx2.MockTransport]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, content=body, headers={"content-type": "application/json"})

    return seen, httpx2.MockTransport(handler)


def _openai(api: str) -> Capture:
    fixture = "response_text.json" if api == "responses" else "chat/text.json"

    async def capture(request: LLMRequest) -> bytes:
        seen, transport = _respond((FIXTURES / "openai" / fixture).read_bytes())
        client = AsyncOpenAI(
            api_key="sk-test",
            base_url="http://127.0.0.1:11434/v1",
            max_retries=0,
            http_client=httpx2.AsyncClient(transport=transport),
        )
        llm = OpenAILLM(SecretStr("sk-test"), api=api, client=client)  # type: ignore[arg-type]
        await llm.invoke(request)
        return seen[0].content

    return capture


async def _anthropic(request: LLMRequest) -> bytes:
    seen, transport = _respond((FIXTURES / "anthropic" / "message_text.json").read_bytes())
    client = AsyncAnthropic(
        api_key="ant-test", max_retries=0, http_client=httpx2.AsyncClient(transport=transport)
    )
    await AnthropicLLM(SecretStr("ant-test"), client=client).invoke(request)
    return seen[0].content


CAPTURES: dict[str, Capture] = {
    "responses": _openai("responses"),
    "chat_completions": _openai("chat_completions"),
    "anthropic": _anthropic,
}


def text_only() -> LLMRequest:
    """A text-only request touching every input kind and option a 0.8.0 request had."""
    return LLMRequest(
        instructions="be brief",
        input=(
            MessageItem(role=Role.USER, text="Refund order #48213"),
            MessageItem(role=Role.ASSISTANT, text="Looking it up."),
            ToolCallItem(
                call=ToolCall(call_id="call_0", name="orders.get", arguments={"id": "48213"})
            ),
            ToolResultItem(result=ToolResult.text("call_0", "shipped, cracked")),
            MessageItem(role=Role.USER, text="from the sub-task", source="agent"),
        ),
        tools=(
            ToolDefinition(
                name="orders.get", description="Fetch an order", input_schema={"type": "object"}
            ),
        ),
        cache_key="task-1",
        reasoning_effort="low",
    )


# --- text-only bodies are byte-identical to 0.8.0 ------------------------------------------


@pytest.mark.parametrize("api", sorted(CAPTURES))
async def test_text_only_body_is_byte_identical_to_0_8_0(api: str) -> None:
    body = await CAPTURES[api](text_only())
    golden = GOLDEN / f"text_only_{api}.json"
    if os.environ.get("UPDATE_GOLDEN_BODIES") == "1":  # only ever from a 0.8.0 checkout
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_bytes(body)
    assert body == golden.read_bytes()


# --- the content table, row by row ---------------------------------------------------------


def ref(
    kind: MediaKind, media_type: str, *, media_id: str = "m1", name: str = "photo.png"
) -> MediaRef:
    return MediaRef(id=media_id, task_id="t1", kind=kind, media_type=media_type, size=10, name=name)


def image(data: bytes | None = PNG) -> MediaAttachment:
    return MediaAttachment(ref=ref(MediaKind.IMAGE, "image/png"), data=data)


def audio(
    media_type: str = "audio/wav",
    *,
    data: bytes | None = WAV,
    transcript: str | None = None,
    name: str = "note.wav",
) -> MediaAttachment:
    return MediaAttachment(
        ref=ref(MediaKind.AUDIO, media_type, media_id="a1", name=name),
        data=data,
        transcript=transcript,
    )


def with_media(*media: MediaAttachment, text: str = "What is this?") -> LLMRequest:
    return LLMRequest(
        instructions="be brief",
        input=(MessageItem(role=Role.USER, text=text, media=media),),
    )


async def sent(api: str, request: LLMRequest) -> JsonObject:
    return cast(JsonObject, json.loads(await CAPTURES[api](request)))


def _user_content(api: str, body: JsonObject) -> object:
    key = "input" if api == "responses" else "messages"
    messages = cast(list[JsonObject], body[key])
    users = [m for m in messages if m.get("role") == "user"]
    return users[-1]["content"]


def data_url(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode()}"


async def test_responses_maps_text_and_image() -> None:
    body = await sent("responses", with_media(image()))
    assert _user_content("responses", body) == [
        {"type": "input_text", "text": "What is this?"},
        {"type": "input_image", "image_url": data_url(PNG, "image/png"), "detail": "auto"},
    ]


async def test_chat_completions_maps_text_and_image() -> None:
    body = await sent("chat_completions", with_media(image()))
    assert _user_content("chat_completions", body) == [
        {"type": "text", "text": "What is this?"},
        {"type": "image_url", "image_url": {"url": data_url(PNG, "image/png")}},
    ]


async def test_anthropic_maps_text_and_image() -> None:
    body = await sent("anthropic", with_media(image()))
    assert _user_content("anthropic", body) == [
        {"type": "text", "text": "What is this?"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(PNG).decode(),
            },
        },
    ]


@pytest.mark.parametrize(("media_type", "wire"), [("audio/wav", "wav"), ("audio/mpeg", "mp3")])
async def test_chat_completions_sends_native_audio(media_type: str, wire: str) -> None:
    body = await sent("chat_completions", with_media(audio(media_type)))
    assert _user_content("chat_completions", body) == [
        {"type": "text", "text": "What is this?"},
        {
            "type": "input_audio",
            "input_audio": {"data": base64.b64encode(WAV).decode(), "format": wire},
        },
    ]


@pytest.mark.parametrize("api", ["responses", "anthropic"])
async def test_native_audio_is_not_sent_where_the_api_takes_none(api: str) -> None:
    body = await sent(api, with_media(audio()))
    content = cast(list[JsonObject], _user_content(api, body))
    assert [part["type"] for part in content] == ["input_text" if api == "responses" else "text"]


async def test_chat_completions_does_not_send_an_audio_format_it_cannot_carry() -> None:
    body = await sent("chat_completions", with_media(audio("audio/webm", data=WEBM)))
    assert _user_content("chat_completions", body) == [{"type": "text", "text": "What is this?"}]


@pytest.mark.parametrize(
    ("api", "text_type"),
    [("responses", "input_text"), ("chat_completions", "text"), ("anthropic", "text")],
)
async def test_a_transcript_is_sent_as_text(api: str, text_type: str) -> None:
    transcribed = audio(data=None, transcript="what is in the photo?")
    body = await sent(api, with_media(transcribed))
    assert _user_content(api, body) == [
        {"type": text_type, "text": "What is this?"},
        {"type": text_type, "text": "[transcript of note.wav] what is in the photo?"},
    ]


@pytest.mark.parametrize("api", sorted(CAPTURES))
async def test_a_message_of_only_media_has_no_empty_text_part(api: str) -> None:
    body = await sent(api, with_media(image(), text=""))
    content = cast(list[JsonObject], _user_content(api, body))
    assert len(content) == 1
    assert "image" in cast(str, content[0]["type"])


@pytest.mark.parametrize("api", sorted(CAPTURES))
async def test_an_unresolved_image_raises_provider_error(api: str) -> None:
    with pytest.raises(ProviderError, match="media not resolved"):
        await CAPTURES[api](with_media(image(data=None)))


async def test_unresolved_native_audio_raises_provider_error() -> None:
    with pytest.raises(ProviderError, match="media not resolved"):
        await CAPTURES["chat_completions"](with_media(audio(data=None)))


# --- model info ----------------------------------------------------------------------------


def test_model_info_defaults_to_text() -> None:
    info = LLMModelInfo(provider="p", model="m", context_window_tokens=1)
    assert info.input_modalities == frozenset({"text"})
    assert info.output_modalities == frozenset({"text"})
    assert info.audio_input_formats == frozenset()
    assert FakeLLM([]).info.input_modalities == frozenset({"text"})


def test_message_item_media_defaults_to_none() -> None:
    item = MessageItem(role=Role.USER, text="hi")
    assert item.media == ()
    assert "media" not in item.model_dump(exclude_defaults=True)


def test_openai_model_info_follows_the_api() -> None:
    responses = OpenAILLM(SecretStr("sk"), input_modalities=("text", "image"))
    chat = OpenAILLM(
        SecretStr("sk"), api="chat_completions", input_modalities=("text", "image", "audio")
    )
    assert responses.info.input_modalities == frozenset({"text", "image"})
    assert responses.info.audio_input_formats == frozenset()
    assert chat.info.input_modalities == frozenset({"text", "image", "audio"})
    assert chat.info.audio_input_formats == frozenset({"audio/wav", "audio/mpeg"})
    assert OpenAILLM(SecretStr("sk")).info.input_modalities == frozenset({"text", "image"})
    assert OpenAILLM(SecretStr("sk"), api="chat_completions").info.input_modalities == frozenset(
        {"text"}
    )


def test_anthropic_model_info_takes_images() -> None:
    info = AnthropicLLM(SecretStr("ant")).info
    assert info.input_modalities == frozenset({"text", "image"})
    assert info.audio_input_formats == frozenset()


def test_a_history_with_refs_round_trips() -> None:
    item = MessageItem(role=Role.USER, text="see", media=(image(data=None),))
    assert MessageItem.model_validate_json(item.model_dump_json()) == item
