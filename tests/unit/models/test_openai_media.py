"""T1: the OpenAI speech and image implementations (issue-38 R5.3, R5.4, R5.7).

Each runs over a client from the LLM adapter's own factory (``max_retries=0``, an explicit
``base_url``, no redirects), so requests reach only the configured host, durable execution
owns retrying, and errors map as the LLM adapter maps them. HTTP is a recording
``httpx2.MockTransport``: no request leaves the process.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import timedelta

import httpx2
import pytest
from pydantic import SecretStr

from tiny_harness.errors import ProviderError, RetryableProviderError
from tiny_harness.harness.media import AudioFormat
from tiny_harness.harness.models.images import blank_png
from tiny_harness.harness.models.openai_adapter import DEFAULT_BASE_URL, openai_client
from tiny_harness.harness.models.openai_media import (
    OpenAIImageGenerator,
    OpenAISpeechToText,
    OpenAITextToSpeech,
)

LOCAL = "http://127.0.0.1:11434/v1"
Handler = Callable[[httpx2.Request], httpx2.Response]


class Recorder:
    def __init__(self, respond: Handler) -> None:
        self.requests: list[httpx2.Request] = []
        self._respond = respond

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._respond(request)

    def client(self, *, base_url: str | None = LOCAL, api_key: str | None = "sk-test"):
        key = SecretStr(api_key) if api_key is not None else None
        return openai_client(
            key,
            base_url=base_url,
            timeout=timedelta(seconds=5),
            transport=httpx2.MockTransport(self),
        )


def transcript_ok(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"text": "what is in the photo?"})


PCM = b"\x01\x00\x02\x00" * 1_000


def speech_ok(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, content=PCM, headers={"content-type": "application/octet-stream"})


PNG = blank_png(64, 32)


def image_ok(_: httpx2.Request) -> httpx2.Response:
    body = {
        "created": 0,
        "data": [{"b64_json": base64.b64encode(PNG).decode(), "revised_prompt": "a green sofa"}],
    }
    return httpx2.Response(200, json=body)


def stt(recorder: Recorder, **kwargs: str | None) -> OpenAISpeechToText:
    api_key = kwargs.pop("api_key", "sk-test")
    base_url = kwargs.pop("base_url", LOCAL)
    key = SecretStr(api_key) if api_key is not None else None
    return OpenAISpeechToText(
        key,
        base_url=base_url,
        client=recorder.client(base_url=base_url, api_key=api_key),
    )


def tts(recorder: Recorder) -> OpenAITextToSpeech:
    return OpenAITextToSpeech(
        SecretStr("sk-test"), base_url=LOCAL, voice="coral", client=recorder.client()
    )


def images(recorder: Recorder) -> OpenAIImageGenerator:
    return OpenAIImageGenerator(SecretStr("sk-test"), base_url=LOCAL, client=recorder.client())


# --- request shapes ------------------------------------------------------------------------


async def test_transcribe_sends_the_file_to_the_transcriptions_endpoint() -> None:
    recorder = Recorder(transcript_ok)
    transcript = await stt(recorder).transcribe(
        b"RIFF-audio", media_type="audio/wav", name="note.wav", language="en"
    )
    assert transcript.text == "what is in the photo?"
    assert transcript.language == "en"
    sent = recorder.requests[0]
    assert str(sent.url) == f"{LOCAL}/audio/transcriptions"
    body = sent.content
    assert b'name="model"' in body and b"gpt-4o-mini-transcribe" in body
    assert b'filename="note.wav"' in body and b"Content-Type: audio/wav" in body
    assert b"RIFF-audio" in body
    assert b'name="language"' in body


async def test_transcribe_sends_no_language_unless_given() -> None:
    recorder = Recorder(transcript_ok)
    await stt(recorder).transcribe(b"x", media_type="audio/webm")
    assert b'name="language"' not in recorder.requests[0].content


async def test_speech_streams_pcm_chunks() -> None:
    recorder = Recorder(speech_ok)
    speaker = tts(recorder)
    assert speaker.format == AudioFormat(encoding="pcm_s16le", sample_rate=24_000, channels=1)
    chunks = [c async for c in speaker.stream("Hello there.", instructions="warm")]
    assert b"".join(chunks) == PCM
    sent = recorder.requests[0]
    assert str(sent.url) == f"{LOCAL}/audio/speech"
    assert json.loads(sent.content) == {
        "model": "gpt-4o-mini-tts",
        "voice": "coral",
        "input": "Hello there.",
        "response_format": "pcm",
        "instructions": "warm",
    }


async def test_speech_voice_can_be_chosen_per_call_and_empty_instructions_are_omitted() -> None:
    recorder = Recorder(speech_ok)
    async for _ in tts(recorder).stream("Hi", voice="sage", instructions=""):
        pass
    body = json.loads(recorder.requests[0].content)
    assert body["voice"] == "sage"
    assert "instructions" not in body


async def test_generate_decodes_the_png() -> None:
    recorder = Recorder(image_ok)
    image = await images(recorder).generate("a green sofa", size="1536x1024")
    assert (image.data, image.media_type) == (PNG, "image/png")
    assert (image.width, image.height) == (64, 32)  # read from the image, not the request
    assert image.revised_prompt == "a green sofa"
    sent = recorder.requests[0]
    assert str(sent.url) == f"{LOCAL}/images/generations"
    assert json.loads(sent.content) == {
        "model": "gpt-image-2",
        "prompt": "a green sofa",
        "size": "1536x1024",
        "output_format": "png",
        "n": 1,
    }


async def test_generate_uses_the_default_size() -> None:
    recorder = Recorder(image_ok)
    await images(recorder).generate("x")
    assert json.loads(recorder.requests[0].content)["size"] == "1024x1024"


async def test_an_image_response_without_bytes_is_a_provider_error() -> None:
    recorder = Recorder(lambda _: httpx2.Response(200, json={"created": 0, "data": [{}]}))
    with pytest.raises(ProviderError):
        await images(recorder).generate("x")


async def test_an_image_that_is_not_a_png_is_a_provider_error() -> None:
    body = {"created": 0, "data": [{"b64_json": base64.b64encode(b"<svg/>").decode()}]}
    recorder = Recorder(lambda _: httpx2.Response(200, json=body))
    with pytest.raises(ProviderError):
        await images(recorder).generate("x")


# --- the endpoint: base_url only, no retries, no redirects ---------------------------------


async def test_without_a_base_url_requests_go_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://evil.invalid/v1")
    recorder = Recorder(transcript_ok)
    await stt(recorder, base_url=None).transcribe(b"x", media_type="audio/wav")
    assert str(recorder.requests[0].url) == f"{DEFAULT_BASE_URL}/audio/transcriptions"


async def test_a_keyless_endpoint_gets_no_authorization_header() -> None:
    recorder = Recorder(transcript_ok)
    await stt(recorder, api_key=None).transcribe(b"x", media_type="audio/wav")
    assert "authorization" not in recorder.requests[0].headers


def test_a_key_or_a_base_url_is_required() -> None:
    with pytest.raises(ValueError, match="api_key"):
        OpenAISpeechToText(None)


def test_entities_built_without_a_client_use_the_factory() -> None:
    for entity in (
        OpenAISpeechToText(SecretStr("k"), base_url=LOCAL),
        OpenAITextToSpeech(SecretStr("k"), base_url=LOCAL),
        OpenAIImageGenerator(SecretStr("k"), base_url=LOCAL),
    ):
        client = entity._client  # pyright: ignore[reportPrivateUsage]
        assert client.max_retries == 0
        assert str(client.base_url).rstrip("/") == LOCAL
        assert entity.info.endpoint == "http://127.0.0.1:11434"


async def test_abuse_a_redirect_is_refused() -> None:
    recorder = Recorder(
        lambda r: (
            httpx2.Response(200, json={"text": "x"})
            if r.url.host == "elsewhere.invalid"
            else httpx2.Response(307, headers={"location": "http://elsewhere.invalid/v1/audio"})
        )
    )
    with pytest.raises(ProviderError) as caught:
        await stt(recorder).transcribe(b"x", media_type="audio/wav")
    assert caught.value.status == 307
    assert [r.url.host for r in recorder.requests] == ["127.0.0.1"]


# --- error mapping: as the LLM adapter -----------------------------------------------------


def status(code: int) -> Handler:
    return lambda _: httpx2.Response(code, json={"error": {"message": "nope"}})


def refuse(_: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectError("refused")


async def call(kind: str, recorder: Recorder) -> None:
    if kind == "stt":
        await stt(recorder).transcribe(b"x", media_type="audio/wav")
    elif kind == "tts":
        async for _ in tts(recorder).stream("hi"):
            pass
    else:
        await images(recorder).generate("x")


KINDS = ("stt", "tts", "images")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("code", [429, 500, 503])
async def test_rate_limits_and_server_errors_are_retryable_and_not_retried_by_the_sdk(
    kind: str, code: int
) -> None:
    recorder = Recorder(status(code))
    with pytest.raises(RetryableProviderError) as caught:
        await call(kind, recorder)
    assert caught.value.status == code
    assert len(recorder.requests) == 1  # max_retries=0: durable execution retries


@pytest.mark.parametrize("kind", KINDS)
async def test_a_connection_failure_is_retryable(kind: str) -> None:
    with pytest.raises(RetryableProviderError):
        await call(kind, Recorder(refuse))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("code", [400, 401, 404])
async def test_other_statuses_are_provider_errors(kind: str, code: int) -> None:
    with pytest.raises(ProviderError) as caught:
        await call(kind, Recorder(status(code)))
    assert caught.value.status == code
