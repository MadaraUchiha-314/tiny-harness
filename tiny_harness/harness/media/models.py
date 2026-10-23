"""Media references and attachments (issue-38 R1.4, R1.5, R6, NFR durability).

Media bytes live in one task-scoped ``MediaStore``; everything else (A2A events, workflow
history, the ``LLMRequest``) carries a ``MediaRef``. A ``MediaAttachment`` may hold the
bytes only inside an activity, and refuses to serialise while it does, so resolved bytes
cannot reach a workflow payload, a trace or a log by mistake (abuse case 8).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, Self

from pydantic import (
    BaseModel,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)


class MediaKind(StrEnum):
    """What a medium is, as the model sees it."""

    IMAGE = "image"
    AUDIO = "audio"


ACCEPTED: Final[Mapping[str, MediaKind]] = MappingProxyType(
    {
        "image/png": MediaKind.IMAGE,
        "image/jpeg": MediaKind.IMAGE,
        "image/webp": MediaKind.IMAGE,
        "image/gif": MediaKind.IMAGE,
        "audio/wav": MediaKind.AUDIO,
        "audio/mpeg": MediaKind.AUDIO,
        "audio/mp4": MediaKind.AUDIO,
        "audio/ogg": MediaKind.AUDIO,
        "audio/webm": MediaKind.AUDIO,
    }
)
"""The media types accepted as input (R1.4), each with its kind."""

PCM_MEDIA_TYPE: Final = "audio/L16;rate=24000;channels=1"
"""Spoken replies: produced by the server only, never accepted as input."""

_ID: Final = r"^[A-Za-z0-9_-]{1,128}$"
_NAME_MAX: Final = 120


def _kind_of(media_type: str) -> MediaKind | None:
    if media_type == PCM_MEDIA_TYPE:
        return MediaKind.AUDIO
    return ACCEPTED.get(media_type)


def _sanitise_name(name: str) -> str:
    """The basename, without control characters, at most 120 characters: display text
    and a ``Content-Disposition`` value, never a path."""
    base = re.split(r"[/\\]", name)[-1]
    clean = "".join(c for c in base if unicodedata.category(c)[0] != "C")
    return clean.strip()[:_NAME_MAX]


class MediaRef(BaseModel, frozen=True):
    """A stored medium of one task. ``id`` is ``secrets.token_urlsafe(18)`` for stored
    media (144 random bits, not guessable); both ids are restricted to ``[A-Za-z0-9_-]``
    so they are safe in a path (abuse case 4)."""

    id: str = Field(pattern=_ID)
    task_id: str = Field(pattern=_ID)
    kind: MediaKind
    media_type: str = Field(description="a key of ACCEPTED, or PCM_MEDIA_TYPE")
    size: int = Field(ge=0, description="bytes; 0 while a growing object is open")
    name: str = Field(default="", description="original file name, sanitised")
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    voice: bool = Field(default=False, description="recorded by a voice control")

    @field_validator("name", mode="before")
    @classmethod
    def _basename(cls, value: object) -> object:
        return _sanitise_name(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _known_type(self) -> Self:
        kind = _kind_of(self.media_type)
        if kind is None:
            raise ValueError(f"media type {self.media_type!r} is not accepted")
        if kind is not self.kind:
            raise ValueError(f"media type {self.media_type!r} is not of kind {self.kind.value}")
        return self


class MediaAttachment(BaseModel, frozen=True):
    """A medium attached to a message of the conversation. ``data`` is set ONLY inside an
    activity that resolved it; such an attachment cannot be serialised."""

    ref: MediaRef
    transcript: str | None = None
    data: bytes | None = None

    @model_serializer(mode="wrap")
    def _no_bytes(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        if self.data is not None:
            raise ValueError(
                "media bytes are resolved on this attachment; serialise its ref, not the bytes"
            )
        dumped: dict[str, object] = handler(self)
        dumped.pop("data", None)
        return dumped

    def url(self, base: str) -> str:
        """Where the media route serves this medium."""
        return f"{base.rstrip('/')}/media/{self.ref.task_id}/{self.ref.id}"


@dataclass(frozen=True)
class AudioFormat:
    """A raw audio stream's format, e.g. what ``TextToSpeech.stream`` yields."""

    encoding: Literal["pcm_s16le"]
    sample_rate: int
    channels: int

    @property
    def media_type(self) -> str:
        return f"audio/L16;rate={self.sample_rate};channels={self.channels}"


__all__ = [
    "ACCEPTED",
    "PCM_MEDIA_TYPE",
    "AudioFormat",
    "MediaAttachment",
    "MediaKind",
    "MediaRef",
]
