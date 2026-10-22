"""Media configuration (issue-38 R5.5, NFR size limits): ``[media]`` turns media on, the
three provider sections need it, ``[openai]`` states what the model takes, and the request
cap grows to admit a full message of media."""

from __future__ import annotations

import math
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from starlette.applications import Starlette

from tiny_harness.config import (
    ImageGenerationConfig,
    MediaConfig,
    ServerConfig,
    Settings,
    SpeechToTextConfig,
    TextToSpeechConfig,
)
from tiny_harness.errors import ConfigError
from tiny_harness.service.a2a.app import RouteOptions, wrap_middleware
from tiny_harness.service.a2a.middleware import LimitsMiddleware

ENV = {"OPENAI_API_KEY": "sk-secret"}

BASE = """
[temporal]
mode = "embedded"

[server]
base_url = "http://127.0.0.1:8080"

[openai]
{openai}

{rest}
"""


def load(
    tmp_path: Path, rest: str = "", *, openai: str = "", env: dict[str, str] = ENV
) -> Settings:
    path = tmp_path / "config.toml"
    path.write_text(BASE.format(openai=openai, rest=rest))
    return Settings.load(path, env=env)


def refused(
    tmp_path: Path, rest: str = "", *, openai: str = "", env: dict[str, str] = ENV
) -> ConfigError:
    with pytest.raises(ConfigError) as caught:
        load(tmp_path, rest, openai=openai, env=env)
    return caught.value


ALL = """
[media]
max_audio_seconds = 60
dir = "/srv/media"
speech_drain = "PT30S"

[speech_to_text]
provider = "openai"
model = "gpt-4o-mini-transcribe"

[text_to_speech]
provider = "openai"
model = "gpt-4o-mini-tts"
voice = "coral"
instructions = "calm"

[image_generation]
provider = "openai"
model = "gpt-image-2"
size = "1536x1024"

[retention]
media = "P7D"
"""


def test_without_media_everything_is_off(tmp_path: Path) -> None:
    settings = load(tmp_path)
    assert settings.media is None
    assert settings.speech_to_text is None
    assert settings.text_to_speech is None
    assert settings.image_generation is None
    assert settings.retention.media == timedelta(days=30)


def test_media_defaults_match_the_design(tmp_path: Path) -> None:
    media = load(tmp_path, "[media]").media
    assert media is not None
    assert media == MediaConfig()
    assert media.max_file_bytes == 20 * 1024 * 1024
    assert media.max_message_bytes == 25 * 1024 * 1024
    assert media.max_image_pixels == 40_000_000
    assert media.max_audio_seconds == 120
    assert media.dir is None
    assert media.speech_drain == timedelta(seconds=120)


def test_every_media_section_is_read(tmp_path: Path) -> None:
    settings = load(tmp_path, ALL)
    assert settings.media is not None
    assert settings.media.max_audio_seconds == 60
    assert settings.media.dir == Path("/srv/media")
    assert settings.media.speech_drain == timedelta(seconds=30)
    assert settings.speech_to_text == SpeechToTextConfig(model="gpt-4o-mini-transcribe")
    assert settings.text_to_speech == TextToSpeechConfig(instructions="calm", voice="coral")
    assert settings.image_generation == ImageGenerationConfig(size="1536x1024")
    assert settings.retention.media == timedelta(days=7)


def test_an_empty_dir_means_the_default(tmp_path: Path) -> None:
    media = load(tmp_path, '[media]\ndir = ""').media
    assert media is not None and media.dir is None


@pytest.mark.parametrize("section", ["speech_to_text", "text_to_speech", "image_generation"])
def test_provider_sections_require_media(tmp_path: Path, section: str) -> None:
    error = refused(tmp_path, f'[{section}]\nprovider = "openai"')
    assert "[media]" in error.message


def test_an_unknown_provider_is_refused(tmp_path: Path) -> None:
    error = refused(tmp_path, '[media]\n[speech_to_text]\nprovider = "acme"')
    assert error.variable == "speech_to_text.provider"


def test_an_unknown_media_key_is_refused(tmp_path: Path) -> None:
    error = refused(tmp_path, "[media]\nmax_video_seconds = 3")
    assert error.variable == "media.max_video_seconds"


@pytest.mark.parametrize(
    "bad",
    [
        "max_file_bytes = 0",
        "max_audio_seconds = -1",
        "max_image_pixels = 0",
        "max_file_bytes = 30_000_000",  # more than max_message_bytes
        'speech_drain = "PT0S"',
    ],
)
def test_media_limits_must_be_sane(tmp_path: Path, bad: str) -> None:
    refused(tmp_path, f"[media]\n{bad}")


def test_image_size_is_one_the_provider_offers(tmp_path: Path) -> None:
    refused(tmp_path, '[media]\n[image_generation]\nsize = "999x999"')


def test_openai_provider_needs_a_key_or_an_endpoint(tmp_path: Path) -> None:
    error = refused(tmp_path, "[media]\n[speech_to_text]", env={})
    assert error.variable == "OPENAI_API_KEY"
    keyless = load(
        tmp_path,
        "[media]\n[speech_to_text]",
        openai='base_url = "http://127.0.0.1:11434/v1"',
        env={},
    )
    assert keyless.speech_to_text is not None


# --- [openai] input modalities -------------------------------------------------------------


def test_input_modalities_default_by_api(tmp_path: Path) -> None:
    assert load(tmp_path).openai.input_modalities == ("text", "image")
    chat = load(tmp_path, openai='api = "chat_completions"').openai
    assert chat.input_modalities == ("text",)
    assert chat.audio_tokens_per_second == 10


def test_input_modalities_and_audio_rate_are_configurable(tmp_path: Path) -> None:
    config = load(
        tmp_path,
        openai='api = "chat_completions"\ninput_modalities = ["text", "audio"]\n'
        "audio_tokens_per_second = 25",
    ).openai
    assert config.input_modalities == ("text", "audio")
    assert config.audio_tokens_per_second == 25


@pytest.mark.parametrize(
    "bad",
    [
        'input_modalities = ["text", "video"]',
        'input_modalities = ["image"]',
        "input_modalities = []",
        "audio_tokens_per_second = 0",
    ],
)
def test_bad_modalities_are_refused(tmp_path: Path, bad: str) -> None:
    refused(tmp_path, openai=bad)


# --- the effective request cap ------------------------------------------------------------


SERVER = ServerConfig.model_validate({"base_url": "http://127.0.0.1:8080"})


def test_request_cap_admits_a_full_media_message() -> None:
    media = MediaConfig()
    expected = math.ceil(media.max_message_bytes * 4 / 3) + 65_536
    assert media.request_cap(SERVER.max_request_bytes) == expected
    assert media.request_cap(10**9) == 10**9  # a larger configured cap still wins


def test_limits_middleware_uses_the_effective_cap() -> None:
    inner = Starlette()
    text_only = wrap_middleware(inner, config=SERVER, options=RouteOptions())
    assert isinstance(text_only, LimitsMiddleware)
    assert text_only.max_bytes == SERVER.max_request_bytes
    media = MediaConfig()
    with_media = wrap_middleware(inner, config=SERVER, options=RouteOptions(), media=media)
    assert isinstance(with_media, LimitsMiddleware)
    assert with_media.max_bytes == media.request_cap(SERVER.max_request_bytes)


def test_fastapi_router_limits_use_the_effective_cap(tmp_path: Path) -> None:
    from tiny_harness.fastapi import _Limits  # pyright: ignore[reportPrivateUsage]
    from tiny_harness.service.harness import Harness

    settings = load(tmp_path, "[media]")
    limits = _Limits(cast(Harness, SimpleNamespace(settings=settings)))
    assert settings.media is not None
    assert limits.max_bytes == settings.media.request_cap(settings.server.max_request_bytes)
    text_only = _Limits(cast(Harness, SimpleNamespace(settings=load(tmp_path))))
    assert text_only.max_bytes == settings.server.max_request_bytes
