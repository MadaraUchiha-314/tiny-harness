"""The image generation entity (issue-38 R2, R5.4) and its scripted fake.

``ImageGenerator.generate`` returns the image's bytes; the ``generate_image`` tool stores
them in the media store and shows them to the user. Providers raise
``RetryableProviderError`` or ``ProviderError`` like the LLM adapters.
"""

from __future__ import annotations

import struct
import zlib
from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from tiny_harness.harness.entities import Entity, EntityKind, EntityRef

DEFAULT_SIZE = "1024x1024"


class ImageModelInfo(BaseModel, frozen=True):
    """Which image model an entity calls, and where (``scheme://host[:port]`` only)."""

    provider: str
    model: str
    endpoint: str | None = None


class GeneratedImage(BaseModel, frozen=True):
    data: bytes
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    width: int
    height: int
    revised_prompt: str | None = None


class ImageGenerator(Entity):
    """Generates one image from a prompt."""

    kind = EntityKind.IMAGE_GENERATOR

    def __init__(self, ref: EntityRef, info: ImageModelInfo) -> None:
        super().__init__(ref)
        self.info = info

    @abstractmethod
    async def generate(self, prompt: str, *, size: str | None = None) -> GeneratedImage: ...


def parse_size(size: str) -> tuple[int, int]:
    """``"1536x1024"`` → ``(1536, 1024)``."""
    width, _, height = size.partition("x")
    return int(width), int(height)


def blank_png(width: int, height: int) -> bytes:
    """A valid, all-black grayscale PNG of the given size (stdlib only)."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = (b"\x00" + b"\x00" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


@dataclass(frozen=True)
class GenerateCall:
    """One call a ``FakeImageGenerator`` saw."""

    prompt: str
    size: str | None


class FakeImageGenerator(ImageGenerator):
    """Returns scripted images (or raises scripted errors) in order; with none left, a
    blank PNG of the requested size. Records calls."""

    def __init__(self, images: Sequence[GeneratedImage | Exception] = ()) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.IMAGE_GENERATOR, id="fake", version=None),
            ImageModelInfo(provider="fake", model="fake-image"),
        )
        self._script = list(images)
        self.calls: list[GenerateCall] = []

    async def generate(self, prompt: str, *, size: str | None = None) -> GeneratedImage:
        self.calls.append(GenerateCall(prompt, size))
        if self._script:
            result = self._script.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        width, height = parse_size(size or DEFAULT_SIZE)
        return GeneratedImage(
            data=blank_png(width, height), media_type="image/png", width=width, height=height
        )


__all__ = [
    "DEFAULT_SIZE",
    "FakeImageGenerator",
    "GenerateCall",
    "GeneratedImage",
    "ImageGenerator",
    "ImageModelInfo",
    "blank_png",
    "parse_size",
]
