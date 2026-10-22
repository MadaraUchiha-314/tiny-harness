"""Content checks for untrusted media, stdlib only (issue-38 R1.4, abuse cases 2 and 7).

``detect`` names a file's type from its signature, never from its name or declared type.
``image_size`` reads an image's dimensions from its header without decoding a pixel, so a
decompression bomb is refused by its declared size. Every parser here is bounded: it hops
from header to header with a hop budget and fails closed (``SniffError``) on anything it
cannot account for.
"""

from __future__ import annotations

import struct
from typing import Final, Literal

SniffReason = Literal["unreadable", "not_audio_only", "audio_too_long", "audio_duration_unknown"]


class SniffError(ValueError):
    """A file whose header cannot be read, or whose content the checks refuse."""

    def __init__(self, reason: SniffReason, message: str) -> None:
        super().__init__(message)
        self.reason: SniffReason = reason


def _unreadable(what: str) -> SniffError:
    return SniffError("unreadable", f"{what}: header cannot be read")


# --- signatures ----------------------------------------------------------------------------

_PNG: Final = b"\x89PNG\r\n\x1a\n"
_EBML: Final = b"\x1a\x45\xdf\xa3"
_EBML_DOCTYPE: Final = 0x4282
_EBML_HEADER_HOPS: Final = 32


def _is_mpeg_frame(head: bytes) -> bool:
    """An MPEG audio frame header: 11 sync bits, a version and a layer that are not
    reserved, a bitrate index that is neither free (0, unwalkable) nor bad (15) and a
    sample-rate index that is not reserved (3)."""
    if len(head) < 4 or head[0] != 0xFF or head[1] & 0xE0 != 0xE0:
        return False
    version = (head[1] >> 3) & 0x03
    layer = (head[1] >> 1) & 0x03
    bitrate = head[2] >> 4
    rate = (head[2] >> 2) & 0x03
    return version != 1 and layer != 0 and bitrate not in (0x00, 0x0F) and rate != 0x03


def _ebml_doctype(raw: bytes) -> str | None:
    """The DocType of an EBML header (``webm`` or ``matroska``), or ``None``."""
    try:
        size, pos = _ebml_size(raw, len(_EBML))
    except SniffError:
        return None
    end = min(len(raw), pos + (size if size is not None else len(raw)))
    for _ in range(_EBML_HEADER_HOPS):
        if pos >= end:
            return None
        try:
            element, pos = _ebml_id(raw, pos)
            length, pos = _ebml_size(raw, pos)
        except SniffError:
            return None
        if length is None:
            return None
        if element == _EBML_DOCTYPE:
            return raw[pos : pos + length].rstrip(b"\x00").decode("ascii", "replace")
        pos += length
    return None


def detect(raw: bytes) -> str | None:
    """The accepted media type ``raw`` carries by its signature, or ``None``."""
    if raw.startswith(_PNG):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        return "audio/wav"
    if raw.startswith(b"ID3") or _is_mpeg_frame(raw[:4]):
        return "audio/mpeg"
    if raw[4:8] == b"ftyp":
        return "audio/mp4"
    if raw.startswith(b"OggS"):
        return "audio/ogg"
    if raw.startswith(_EBML) and _ebml_doctype(raw) == "webm":
        return "audio/webm"
    return None


# --- image dimensions ----------------------------------------------------------------------

_JPEG_HOPS: Final = 1024
# SOF0-SOF15 less DHT (C4), JPG (C8) and DAC (CC), which share the range.
_JPEG_SOF: Final = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_JPEG_STANDALONE: Final = frozenset({0x01, *range(0xD0, 0xD8)})


def _png_size(raw: bytes) -> tuple[int, int]:
    if len(raw) < 24 or raw[12:16] != b"IHDR":
        raise _unreadable("png")
    width, height = struct.unpack(">II", raw[16:24])
    return width, height


def _jpeg_size(raw: bytes) -> tuple[int, int]:
    pos = 2
    for _ in range(_JPEG_HOPS):
        while pos < len(raw) and raw[pos] == 0xFF and pos + 1 < len(raw) and raw[pos + 1] == 0xFF:
            pos += 1  # fill bytes
        if pos + 2 > len(raw) or raw[pos] != 0xFF:
            raise _unreadable("jpeg")
        marker = raw[pos + 1]
        pos += 2
        if marker in _JPEG_STANDALONE:
            continue
        if marker in (0xD9, 0xDA):  # end of image, or a scan before any frame header
            raise _unreadable("jpeg")
        if pos + 2 > len(raw):
            raise _unreadable("jpeg")
        (length,) = struct.unpack(">H", raw[pos : pos + 2])
        if length < 2 or pos + length > len(raw):
            raise _unreadable("jpeg")
        if marker in _JPEG_SOF:
            if length < 7:
                raise _unreadable("jpeg")
            height, width = struct.unpack(">HH", raw[pos + 3 : pos + 7])
            return width, height
        pos += length
    raise _unreadable("jpeg")


def _gif_size(raw: bytes) -> tuple[int, int]:
    if len(raw) < 10:
        raise _unreadable("gif")
    width, height = struct.unpack("<HH", raw[6:10])
    return width, height


def _webp_size(raw: bytes) -> tuple[int, int]:
    chunk = raw[12:16]
    data = raw[20:]
    if chunk == b"VP8 " and len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", data[6:10])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 5 and data[0] == 0x2F:
        (bits,) = struct.unpack("<I", data[1:5])
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X" and len(data) >= 10:
        width = int.from_bytes(data[4:7], "little") + 1
        height = int.from_bytes(data[7:10], "little") + 1
        return width, height
    raise _unreadable("webp")


def image_size(raw: bytes) -> tuple[int, int]:
    """``(width, height)`` from the image's header; ``SniffError`` when it cannot be read."""
    match detect(raw):
        case "image/png":
            return _png_size(raw)
        case "image/jpeg":
            return _jpeg_size(raw)
        case "image/gif":
            return _gif_size(raw)
        case "image/webp":
            return _webp_size(raw)
        case _:
            raise _unreadable("image")


# --- EBML (WebM) primitives ----------------------------------------------------------------


def _ebml_vint(raw: bytes, pos: int, *, keep_marker: bool) -> tuple[int, int, int]:
    """One EBML variable-length integer at ``pos``: ``(value, width, next position)``."""
    if pos >= len(raw):
        raise _unreadable("webm")
    first = raw[pos]
    width = 1
    mask = 0x80
    while width <= 8 and not first & mask:
        width += 1
        mask >>= 1
    if width > 8 or pos + width > len(raw):
        raise _unreadable("webm")
    value = first if keep_marker else first & (mask - 1)
    for byte in raw[pos + 1 : pos + width]:
        value = (value << 8) | byte
    return value, width, pos + width


def _ebml_id(raw: bytes, pos: int) -> tuple[int, int]:
    value, width, nxt = _ebml_vint(raw, pos, keep_marker=True)
    if width > 4:
        raise _unreadable("webm")
    return value, nxt


def _ebml_size(raw: bytes, pos: int) -> tuple[int | None, int]:
    """An element's data size; ``None`` for the reserved "unknown size" value."""
    value, width, nxt = _ebml_vint(raw, pos, keep_marker=False)
    if value == (1 << (7 * width)) - 1:
        return None, nxt
    return value, nxt


__all__ = ["SniffError", "SniffReason", "detect", "image_size"]
