"""Speech entities (issue-38 R5.3): speech-to-text for voice input, text-to-speech for
spoken replies, and their scripted fakes.

``SpeechToText.transcribe`` turns one audio file into a ``Transcript``. ``TextToSpeech.stream``
yields raw audio in its declared ``format`` as the provider produces it, so a spoken reply
can play while it is still being generated. Providers raise ``RetryableProviderError`` for
what durable execution may retry and ``ProviderError`` otherwise, like the LLM adapters.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from tiny_harness.harness.entities import Entity, EntityKind, EntityRef
from tiny_harness.harness.media.models import AudioFormat

PCM_24K_MONO = AudioFormat(encoding="pcm_s16le", sample_rate=24_000, channels=1)
"""What OpenAI's ``pcm`` speech format is: 16-bit little-endian, 24 kHz, mono."""


class SpeechModelInfo(BaseModel, frozen=True):
    """Which speech model an entity calls, and where (``scheme://host[:port]`` only)."""

    provider: str
    model: str
    endpoint: str | None = None


class Transcript(BaseModel, frozen=True):
    text: str
    language: str | None = None
    duration_ms: int | None = None


class SpeechToText(Entity):
    """Transcribes one audio file."""

    kind = EntityKind.SPEECH_TO_TEXT

    def __init__(self, ref: EntityRef, info: SpeechModelInfo) -> None:
        super().__init__(ref)
        self.info = info

    @abstractmethod
    async def transcribe(
        self, audio: bytes, *, media_type: str, name: str = "audio", language: str | None = None
    ) -> Transcript: ...


class TextToSpeech(Entity):
    """Speaks a text as a stream of raw audio chunks in ``format``."""

    kind = EntityKind.TEXT_TO_SPEECH

    def __init__(self, ref: EntityRef, info: SpeechModelInfo, format: AudioFormat) -> None:
        super().__init__(ref)
        self.info = info
        self.format = format

    @abstractmethod
    def stream(
        self, text: str, *, voice: str | None = None, instructions: str | None = None
    ) -> AsyncIterator[bytes]: ...


@dataclass(frozen=True)
class TranscribeCall:
    """One call a ``FakeSpeechToText`` saw."""

    audio: bytes
    media_type: str
    name: str
    language: str | None


@dataclass(frozen=True)
class SpeakCall:
    """One call a ``FakeTextToSpeech`` saw."""

    text: str
    voice: str | None
    instructions: str | None


class FakeSpeechToText(SpeechToText):
    """Returns scripted transcripts (or raises scripted errors) in order; records calls."""

    def __init__(self, transcripts: Sequence[Transcript | str | Exception] = ()) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.SPEECH_TO_TEXT, id="fake", version=None),
            SpeechModelInfo(provider="fake", model="fake-stt"),
        )
        self._script = list(transcripts)
        self.calls: list[TranscribeCall] = []

    async def transcribe(
        self, audio: bytes, *, media_type: str, name: str = "audio", language: str | None = None
    ) -> Transcript:
        self.calls.append(TranscribeCall(audio, media_type, name, language))
        if not self._script:
            raise RuntimeError("FakeSpeechToText has no scripted transcript left")
        result = self._script.pop(0)
        if isinstance(result, Exception):
            raise result
        return Transcript(text=result) if isinstance(result, str) else result


class FakeTextToSpeech(TextToSpeech):
    """Yields ``chunks`` (default: 0.1 s of silence) for every text, ``delay`` seconds
    apart, then raises ``error`` when one is scripted; records calls."""

    def __init__(
        self,
        chunks: Sequence[bytes] | None = None,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.TEXT_TO_SPEECH, id="fake", version=None),
            SpeechModelInfo(provider="fake", model="fake-tts"),
            PCM_24K_MONO,
        )
        self.chunks = tuple(chunks) if chunks is not None else (b"\x00\x00" * 2_400,)
        self.error = error
        self.delay = delay
        self.calls: list[SpeakCall] = []

    async def stream(
        self, text: str, *, voice: str | None = None, instructions: str | None = None
    ) -> AsyncIterator[bytes]:
        self.calls.append(SpeakCall(text, voice, instructions))
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk
        if self.error is not None:
            raise self.error


__all__ = [
    "PCM_24K_MONO",
    "FakeSpeechToText",
    "FakeTextToSpeech",
    "SpeakCall",
    "SpeechModelInfo",
    "SpeechToText",
    "TextToSpeech",
    "TranscribeCall",
    "Transcript",
]
