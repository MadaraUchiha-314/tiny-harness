"""The media extension v1 (issue-38 R5.5, R5.6): what the agent card declares when
``[media]`` is set, and the metadata a file part and a message may carry.

The card's ``params`` are the instance's effective media capabilities, so a surface shows
the attach, microphone and speaker controls only where they work. The published JSON
Schema (``docs/a2a/ext/media.json``) is ``media_extension_schema()``.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from tiny_harness.harness.media.effective import MediaCapabilities

MEDIA_EXT_URI: Final = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/media/v1"
MEDIA_ROUTE: Final = "/media"


class MediaExtensionParams(BaseModel, frozen=True):
    """The media extension's card ``params``: the media types this agent accepts and
    produces, its limits, which media services it has, and where its media route is
    (``<agent URL><mediaPath>/<taskId>/<mediaId>``)."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", alias_generator=to_camel, populate_by_name=True
    )

    input: tuple[str, ...] = Field(
        default=(), description="media types accepted in a file part of a new message"
    )
    output: tuple[str, ...] = Field(
        default=(),
        description="media types the agent produces (image/png: generated images; "
        "audio/L16;rate=24000;channels=1: spoken replies)",
    )
    max_file_bytes: int = Field(default=0, ge=0, description="largest file part, in bytes")
    max_message_bytes: int = Field(
        default=0, ge=0, description="largest total of a message's file parts, in bytes"
    )
    max_audio_seconds: int = Field(default=0, ge=0, description="longest audio file, in seconds")
    speech_to_text: bool = Field(default=False, description="audio is transcribed")
    text_to_speech: bool = Field(
        default=False, description="replies to a message with speak=true are spoken"
    )
    image_generation: bool = Field(default=False, description="the agent can generate images")
    media_path: str = Field(
        default=MEDIA_ROUTE, description="the media route's path, relative to the agent's URL"
    )


class MediaPartMetadata(BaseModel, frozen=True):
    """A file part's metadata. A surface may set ``voice`` and ``durationMs`` on a recording;
    the server adds ``mediaId`` and ``size`` (and ``durationMs``, ``width``, ``height``
    where known) when it stores the file and rewrites the part to a media URL. Other keys
    may be present."""

    model_config = ConfigDict(
        frozen=True, extra="allow", alias_generator=to_camel, populate_by_name=True
    )

    media_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$", description="the stored medium's id"
    )
    size: int | None = Field(default=None, ge=0, description="bytes")
    duration_ms: int | None = Field(default=None, ge=0, description="audio duration")
    width: int | None = Field(default=None, ge=0, description="image width, in pixels")
    height: int | None = Field(default=None, ge=0, description="image height, in pixels")
    voice: bool | None = Field(
        default=None, description="recorded by a voice control: its transcript is shown"
    )


class MediaMessageMetadata(BaseModel, frozen=True):
    """A message's metadata: ``speak`` is the surface's speaker setting when it sent the
    message; ``true`` asks for the reply to be spoken. Other keys may be present."""

    model_config = ConfigDict(frozen=True, extra="allow")

    speak: bool | None = Field(default=None, description="speak the reply to this message")


def media_params(capabilities: MediaCapabilities) -> MediaExtensionParams:
    """The card params of the effective capabilities."""
    return MediaExtensionParams(
        input=capabilities.input,
        output=capabilities.output,
        max_file_bytes=capabilities.max_file_bytes,
        max_message_bytes=capabilities.max_message_bytes,
        max_audio_seconds=capabilities.max_audio_seconds,
        speech_to_text=capabilities.speech_to_text,
        text_to_speech=capabilities.text_to_speech,
        image_generation=capabilities.image_generation,
    )


def media_extension_schema() -> dict[str, object]:
    """The published JSON Schema (``docs/a2a/ext/media.json``): the card params, with the
    part and message metadata under ``$defs``."""
    schema = MediaExtensionParams.model_json_schema(by_alias=True)
    defs = schema.setdefault("$defs", {})
    for model in (MediaPartMetadata, MediaMessageMetadata):
        defs[model.__name__] = model.model_json_schema(by_alias=True)
    schema["$id"] = f"{MEDIA_EXT_URI}/schema.json"
    return schema


__all__ = [
    "MEDIA_EXT_URI",
    "MEDIA_ROUTE",
    "MediaExtensionParams",
    "MediaMessageMetadata",
    "MediaPartMetadata",
    "media_extension_schema",
    "media_params",
]
