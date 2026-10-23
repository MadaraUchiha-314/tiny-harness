"""T1: the speech and image interfaces and their scripted fakes (issue-38 R5.3, R5.4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tiny_harness.errors import ProviderError
from tiny_harness.harness.entities import EntityKind
from tiny_harness.harness.media import AudioFormat
from tiny_harness.harness.media.sniff import detect, image_size
from tiny_harness.harness.models import (
    FakeImageGenerator,
    FakeSpeechToText,
    FakeTextToSpeech,
    GeneratedImage,
    ImageGenerator,
    ImageModelInfo,
    SpeechModelInfo,
    SpeechToText,
    TextToSpeech,
    Transcript,
)


def test_each_interface_is_its_own_entity_kind() -> None:
    assert SpeechToText.kind is EntityKind.SPEECH_TO_TEXT
    assert TextToSpeech.kind is EntityKind.TEXT_TO_SPEECH
    assert ImageGenerator.kind is EntityKind.IMAGE_GENERATOR
    assert isinstance(FakeSpeechToText().info, SpeechModelInfo)
    assert isinstance(FakeImageGenerator().info, ImageModelInfo)


async def test_fake_stt_returns_scripted_transcripts_in_order_and_records_calls() -> None:
    stt = FakeSpeechToText([Transcript(text="one"), "two"])
    first = await stt.transcribe(b"a", media_type="audio/wav", name="a.wav")
    second = await stt.transcribe(b"bb", media_type="audio/webm", language="en")
    assert (first.text, second.text) == ("one", "two")
    assert [(c.audio, c.media_type, c.name, c.language) for c in stt.calls] == [
        (b"a", "audio/wav", "a.wav", None),
        (b"bb", "audio/webm", "audio", "en"),
    ]
    with pytest.raises(RuntimeError, match="no scripted transcript"):
        await stt.transcribe(b"c", media_type="audio/wav")


async def test_fake_stt_raises_a_scripted_error() -> None:
    stt = FakeSpeechToText([ProviderError("bad audio", provider="fake", status=400)])
    with pytest.raises(ProviderError, match="bad audio"):
        await stt.transcribe(b"a", media_type="audio/wav")


async def test_fake_tts_streams_its_chunks_in_the_declared_format() -> None:
    tts = FakeTextToSpeech(chunks=(b"\x01\x00" * 4, b"\x02\x00" * 4))
    assert tts.format == AudioFormat(encoding="pcm_s16le", sample_rate=24_000, channels=1)
    chunks = [c async for c in tts.stream("hello", voice="coral", instructions="calm")]
    assert chunks == [b"\x01\x00" * 4, b"\x02\x00" * 4]
    assert [(c.text, c.voice, c.instructions) for c in tts.calls] == [("hello", "coral", "calm")]


async def test_fake_tts_fails_after_its_chunks_when_scripted() -> None:
    tts = FakeTextToSpeech(
        chunks=(b"\x00\x00",), error=ProviderError("x", provider="f", status=500)
    )
    seen: list[bytes] = []
    with pytest.raises(ProviderError):
        async for chunk in tts.stream("hello"):
            seen.append(chunk)
    assert seen == [b"\x00\x00"]


async def test_fake_image_generator_returns_a_real_png_by_default() -> None:
    images = FakeImageGenerator()
    image = await images.generate("a green sofa", size="1536x1024")
    assert image.media_type == "image/png"
    assert detect(image.data) == "image/png"
    assert image_size(image.data) == (image.width, image.height) == (1536, 1024)
    assert [(c.prompt, c.size) for c in images.calls] == [("a green sofa", "1536x1024")]


async def test_fake_image_generator_returns_scripted_images_and_errors() -> None:
    scripted = GeneratedImage(data=b"x", media_type="image/webp", width=1, height=1)
    images = FakeImageGenerator([scripted, ProviderError("policy", provider="f", status=400)])
    assert await images.generate("one") == scripted
    with pytest.raises(ProviderError):
        await images.generate("two")


def test_generated_image_types_are_limited() -> None:
    with pytest.raises(ValidationError):
        GeneratedImage(data=b"x", media_type="image/svg+xml", width=1, height=1)  # type: ignore[arg-type]
