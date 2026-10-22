"""OpenAI speech-to-text, text-to-speech and image generation (issue-38 R5.3, R5.4, R5.7).

All three run over a client from the LLM adapter's own factory (``openai_client``):
``max_retries=0``, so durable execution owns retrying; an explicit ``base_url``, so the
SDK never reads ``OPENAI_BASE_URL``; and, for a custom endpoint, no redirects. Errors map
as the LLM adapter maps them: 429, 5xx, timeouts and connection failures raise
``RetryableProviderError``, any other provider error ``ProviderError``. Speech is
requested as ``pcm`` (16-bit little-endian, 24 kHz, mono) and yielded as it arrives.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import AsyncIterator, Mapping
from datetime import timedelta
from typing import cast

from openai import AsyncOpenAI, Omit, omit
from pydantic import SecretStr

from tiny_harness.errors import ProviderError
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import sniff
from tiny_harness.harness.models.images import (
    DEFAULT_SIZE,
    GeneratedImage,
    ImageGenerator,
    ImageModelInfo,
)
from tiny_harness.harness.models.openai_adapter import (
    PROVIDER,
    endpoint_origin,
    openai_client,
    translate_error,
)
from tiny_harness.harness.models.speech import (
    PCM_24K_MONO,
    SpeechModelInfo,
    SpeechToText,
    TextToSpeech,
    Transcript,
)


class _Endpoint:
    """The client and per-request headers every OpenAI media entity shares."""

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        base_url: str | None,
        timeout: timedelta,
        client: AsyncOpenAI | None,
    ) -> None:
        if api_key is None and base_url is None:
            raise ValueError("an api_key is required unless base_url is set")
        self.origin = endpoint_origin(base_url)
        self.client = client or openai_client(api_key, base_url=base_url, timeout=timeout)
        # A keyless endpoint: strip the placeholder's Authorization header from each call.
        headers: dict[str, str | Omit] | None = {"Authorization": omit} if api_key is None else None
        self.headers = cast(Mapping[str, str] | None, headers)


class OpenAISpeechToText(SpeechToText):
    """``audio.transcriptions`` (default ``gpt-4o-mini-transcribe``)."""

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        model: str = "gpt-4o-mini-transcribe",
        timeout: timedelta = timedelta(seconds=60),
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        endpoint = _Endpoint(api_key, base_url=base_url, timeout=timeout, client=client)
        super().__init__(
            EntityRef(kind=EntityKind.SPEECH_TO_TEXT, id=f"openai/{model}", version=None),
            SpeechModelInfo(provider=PROVIDER, model=model, endpoint=endpoint.origin),
        )
        self._model = model
        self._client = endpoint.client
        self._headers = endpoint.headers

    async def transcribe(
        self, audio: bytes, *, media_type: str, name: str = "audio", language: str | None = None
    ) -> Transcript:
        try:
            result = await self._client.audio.transcriptions.create(
                model=self._model,
                file=(name, audio, media_type),
                language=language if language is not None else omit,
                extra_headers=self._headers,
            )
            return Transcript(text=result.text, language=language)
        except Exception as exc:
            raise translate_error(exc, api="transcriptions") from exc


class OpenAITextToSpeech(TextToSpeech):
    """``audio.speech`` (default ``gpt-4o-mini-tts``), streamed as ``pcm``."""

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        model: str = "gpt-4o-mini-tts",
        voice: str = "coral",
        instructions: str = "",
        timeout: timedelta = timedelta(seconds=60),
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        endpoint = _Endpoint(api_key, base_url=base_url, timeout=timeout, client=client)
        super().__init__(
            EntityRef(kind=EntityKind.TEXT_TO_SPEECH, id=f"openai/{model}", version=None),
            SpeechModelInfo(provider=PROVIDER, model=model, endpoint=endpoint.origin),
            PCM_24K_MONO,
        )
        self._model = model
        self._voice = voice
        self._instructions = instructions
        self._client = endpoint.client
        self._headers = endpoint.headers

    async def stream(
        self, text: str, *, voice: str | None = None, instructions: str | None = None
    ) -> AsyncIterator[bytes]:
        style = instructions if instructions is not None else self._instructions
        try:
            async with self._client.audio.speech.with_streaming_response.create(
                model=self._model,
                voice=voice or self._voice,
                input=text,
                response_format="pcm",
                instructions=style or omit,
                extra_headers=self._headers,
            ) as response:
                async for chunk in response.iter_bytes():
                    yield chunk
        except Exception as exc:
            raise translate_error(exc, api="speech") from exc


class OpenAIImageGenerator(ImageGenerator):
    """``images.generate`` (default ``gpt-image-2``), one PNG decoded from ``b64_json``."""

    def __init__(
        self,
        api_key: SecretStr | None,
        *,
        model: str = "gpt-image-2",
        size: str = DEFAULT_SIZE,
        timeout: timedelta = timedelta(seconds=120),
        base_url: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        endpoint = _Endpoint(api_key, base_url=base_url, timeout=timeout, client=client)
        super().__init__(
            EntityRef(kind=EntityKind.IMAGE_GENERATOR, id=f"openai/{model}", version=None),
            ImageModelInfo(provider=PROVIDER, model=model, endpoint=endpoint.origin),
        )
        self._model = model
        self._size = size
        self._client = endpoint.client
        self._headers = endpoint.headers

    async def generate(self, prompt: str, *, size: str | None = None) -> GeneratedImage:
        try:
            result = await self._client.images.generate(
                model=self._model,
                prompt=prompt,
                size=cast(object, size or self._size),  # type: ignore[arg-type]
                output_format="png",
                n=1,
                extra_headers=self._headers,
            )
        except Exception as exc:
            raise translate_error(exc, api="images") from exc
        first = result.data[0] if result.data else None
        if first is None or not first.b64_json:
            raise ProviderError(
                "the images response carries no image", provider=PROVIDER, status=200
            )
        try:
            data = base64.b64decode(first.b64_json, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ProviderError(
                "the images response is not base64", provider=PROVIDER, status=200
            ) from exc
        try:
            width, height = sniff.image_size(data) if sniff.detect(data) == "image/png" else (0, 0)
        except sniff.SniffError:
            width = height = 0
        if not (width and height):
            raise ProviderError(
                "the images response is not a readable PNG", provider=PROVIDER, status=200
            )
        return GeneratedImage(
            data=data,
            media_type="image/png",
            width=width,
            height=height,
            revised_prompt=first.revised_prompt,
        )


__all__ = ["OpenAIImageGenerator", "OpenAISpeechToText", "OpenAITextToSpeech"]
