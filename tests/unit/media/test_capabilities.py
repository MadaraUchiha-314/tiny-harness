"""T1: the instance's effective media capabilities and how the runtime builds the media
entities (issue-38 R5.5, design critic 9).

One value, computed once at start, says what the instance accepts and produces: the card,
the intake's allow-list and the surfaces all read it. Audio is advertised only when
something can process it: speech-to-text, or a model that takes that audio natively.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from temporalio.client import Client

from tiny_harness.config import DEFAULT_AGENT_ID, MediaConfig, Settings
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import (
    ACCEPTED,
    PCM_MEDIA_TYPE,
    FileMediaStore,
    MediaCapabilities,
    MediaKind,
    capabilities,
)
from tiny_harness.harness.models import (
    FakeImageGenerator,
    FakeLLM,
    FakeSpeechToText,
    FakeTextToSpeech,
    LLMModelInfo,
    OpenAIImageGenerator,
    OpenAISpeechToText,
    OpenAITextToSpeech,
)
from tiny_harness.service import harness as harness_module
from tiny_harness.service.harness import Harness
from tiny_harness.service.runtime import build_runtime, default_media_root

IMAGES = tuple(t for t, k in ACCEPTED.items() if k is MediaKind.IMAGE)
AUDIO = tuple(t for t, k in ACCEPTED.items() if k is MediaKind.AUDIO)
CONFIG = MediaConfig()


def model(*modalities: str, formats: tuple[str, ...] = ()) -> LLMModelInfo:
    return LLMModelInfo(
        provider="p",
        model="m",
        context_window_tokens=1,
        input_modalities=frozenset(modalities or ("text",)),  # type: ignore[arg-type]
        audio_input_formats=frozenset(formats),
    )


# --- capabilities --------------------------------------------------------------------------


def test_media_off_means_nothing_in_and_nothing_out() -> None:
    caps = capabilities(
        model("text", "image"), FakeSpeechToText(), FakeTextToSpeech(), FakeImageGenerator(), None
    )
    assert caps == MediaCapabilities()
    assert not caps.enabled and caps.input == () and caps.output == ()


def test_images_are_accepted_even_when_the_model_cannot_see_them() -> None:
    """R1.7: an image the model cannot see is accepted and noted; /model may switch."""
    caps = capabilities(model("text"), None, None, None, CONFIG)
    assert caps.enabled
    assert caps.input == IMAGES
    assert caps.output == ()


def test_audio_is_accepted_in_every_type_with_speech_to_text() -> None:
    caps = capabilities(model("text"), FakeSpeechToText(), None, None, CONFIG)
    assert caps.input == IMAGES + AUDIO
    assert caps.speech_to_text


def test_without_speech_to_text_only_the_model_native_audio_formats() -> None:
    native = model("text", "image", "audio", formats=("audio/wav", "audio/mpeg"))
    caps = capabilities(native, None, None, None, CONFIG)
    assert caps.input == (*IMAGES, "audio/wav", "audio/mpeg")
    assert not caps.speech_to_text


def test_native_formats_do_not_count_unless_the_model_takes_audio() -> None:
    """A Chat Completions adapter can carry wav and mp3, but a model configured without
    ``audio`` gets none, so no audio is accepted that nothing can process."""
    caps = capabilities(model("text", formats=("audio/wav",)), None, None, None, CONFIG)
    assert caps.input == IMAGES


def test_output_lists_generated_images_and_speech() -> None:
    caps = capabilities(model("text"), None, FakeTextToSpeech(), FakeImageGenerator(), CONFIG)
    assert caps.output == ("image/png", PCM_MEDIA_TYPE)
    assert caps.text_to_speech and caps.image_generation
    assert caps.output_modalities == ("text",)


def test_limits_come_from_the_config() -> None:
    config = MediaConfig(max_file_bytes=10, max_message_bytes=20, max_audio_seconds=30)
    caps = capabilities(model("text"), None, None, None, config)
    assert (caps.max_file_bytes, caps.max_message_bytes, caps.max_audio_seconds) == (10, 20, 30)


# --- the runtime ---------------------------------------------------------------------------


def settings(tmp_path: Path, agent: str = DEFAULT_AGENT_ID, **sections: object) -> Settings:
    return Settings.model_validate(
        {
            "agent": {"id": agent},
            "temporal": {"mode": "embedded"},
            "openai": {"api_key": "sk-unused"},
            "server": {"bind": "127.0.0.1:8080", "base_url": "http://127.0.0.1:8080"},
            "store": {"sqlite_path": str(tmp_path / "state" / "tiny-harness.sqlite3")},
            **sections,
        }
    )


def all_media(tmp_path: Path) -> Settings:
    return settings(
        tmp_path,
        media={},
        speech_to_text={"model": "stt-x"},
        text_to_speech={"model": "tts-x", "voice": "sage"},
        image_generation={"model": "img-x", "size": "1536x1024"},
    )


def test_the_media_root_defaults_beside_the_store(tmp_path: Path) -> None:
    state = (tmp_path / "state").resolve()
    assert default_media_root(settings(tmp_path, media={})) == state / "media"
    assert default_media_root(settings(tmp_path, "support", media={})) == state / "media-support"
    explicit = tmp_path / "elsewhere"
    assert default_media_root(settings(tmp_path, media={"dir": str(explicit)})) == explicit


async def test_a_text_only_runtime_builds_no_media(tmp_path: Path) -> None:
    runtime = await build_runtime(settings(tmp_path), llm=FakeLLM([]))
    assert runtime.media_store is None and runtime.media_intake is None
    assert (runtime.speech_to_text, runtime.text_to_speech, runtime.image_generator) == (
        None,
        None,
        None,
    )
    assert not runtime.media.enabled


async def test_the_runtime_builds_media_entities_from_config(tmp_path: Path) -> None:
    runtime = await build_runtime(all_media(tmp_path), llm=FakeLLM([]))
    assert isinstance(runtime.media_store, FileMediaStore)
    assert runtime.media_store.root == (tmp_path / "state" / "media").resolve()
    stt, tts, images = runtime.speech_to_text, runtime.text_to_speech, runtime.image_generator
    assert isinstance(stt, OpenAISpeechToText) and stt.info.model == "stt-x"
    assert isinstance(tts, OpenAITextToSpeech) and tts.info.model == "tts-x"
    assert isinstance(images, OpenAIImageGenerator) and images.info.model == "img-x"
    assert runtime.media.speech_to_text and runtime.media.text_to_speech
    assert runtime.media.image_generation
    intake = runtime.media_intake
    assert intake is not None
    assert intake.store is runtime.media_store
    assert intake.accepted == frozenset(runtime.media.input)
    assert intake.base_url == "http://127.0.0.1:8080"


async def test_the_intake_accepts_only_what_can_be_processed(tmp_path: Path) -> None:
    runtime = await build_runtime(settings(tmp_path, media={}), llm=FakeLLM([]))
    assert runtime.media_intake is not None
    assert runtime.media_intake.accepted == frozenset(IMAGES)


async def test_sdk_seams_replace_the_configured_entities(tmp_path: Path) -> None:
    stt, tts, images = FakeSpeechToText(), FakeTextToSpeech(), FakeImageGenerator()
    store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="mine"), tmp_path / "mine")
    runtime = await build_runtime(
        settings(tmp_path, media={}),
        llm=FakeLLM([]),
        speech_to_text=stt,
        text_to_speech=tts,
        image_generator=images,
        media_store=store,
        public_url="http://h/agents/a",
    )
    assert runtime.speech_to_text is stt and runtime.text_to_speech is tts
    assert runtime.image_generator is images and runtime.media_store is store
    assert runtime.media.speech_to_text and runtime.media.image_generation
    assert runtime.media_intake is not None
    assert runtime.media_intake.base_url == "http://h/agents/a"


async def test_the_harness_passes_its_seams_to_the_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    class Stop(Exception):
        pass

    async def record(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(harness_module, "build_runtime", record)
    stt, tts, images = FakeSpeechToText(), FakeTextToSpeech(), FakeImageGenerator()
    store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="mine"), tmp_path / "mine")

    class NamespacedClient:
        namespace = "default"

    harness = Harness(
        settings(tmp_path, media={}),
        client=cast(Client, NamespacedClient()),
        speech_to_text=stt,
        text_to_speech=tts,
        image_generator=images,
        media_store=store,
    )
    with pytest.raises(Stop):
        await harness.__aenter__()
    assert seen["speech_to_text"] is stt and seen["text_to_speech"] is tts
    assert seen["image_generator"] is images and seen["media_store"] is store
