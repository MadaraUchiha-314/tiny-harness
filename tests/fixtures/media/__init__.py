"""Small media files built in code (issue-38 T1/T8): one valid file per accepted type and
the forged ones the abuse cases need. Built rather than committed, so each test states the
header values it depends on."""

from __future__ import annotations

import struct
import zlib

# --- images --------------------------------------------------------------------------------


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def png(width: int = 2, height: int = 3, *, padding: int = 0) -> bytes:
    """A PNG whose IHDR declares ``width`` x ``height``; ``padding`` adds an opaque
    ancillary chunk so a small file can declare huge dimensions (a bomb)."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    body = _png_chunk(b"IHDR", ihdr)
    if padding:
        body += _png_chunk(b"tEXt", b"x" * padding)
    body += _png_chunk(b"IDAT", zlib.compress(b"\x00" * 8))
    return b"\x89PNG\r\n\x1a\n" + body + _png_chunk(b"IEND", b"")


def jpeg(width: int = 4, height: int = 5, *, sof: int = 0xC0) -> bytes:
    """A JPEG skeleton: SOI, an APP0, a DQT, the SOF marker ``sof``, SOS, EOI."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    dqt = b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + b"\x01" * 64
    frame = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    sofn = bytes([0xFF, sof]) + struct.pack(">H", len(frame) + 2) + frame
    sos = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00" + b"\x00\x00"
    return b"\xff\xd8" + app0 + dqt + sofn + sos + b"\xff\xd9"


def gif(width: int = 6, height: int = 7, *, version: bytes = b"89a") -> bytes:
    return b"GIF" + version + struct.pack("<HH", width, height) + b"\x00\x00\x00" + b"\x3b"


def _riff(form: bytes, chunks: bytes) -> bytes:
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + form + chunks


def _riff_chunk(kind: bytes, data: bytes) -> bytes:
    pad = b"\x00" if len(data) % 2 else b""
    return kind + struct.pack("<I", len(data)) + data + pad


def webp_vp8(width: int = 8, height: int = 9) -> bytes:
    frame = b"\x10\x02\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\x00" * 4
    return _riff(b"WEBP", _riff_chunk(b"VP8 ", frame))


def webp_vp8l(width: int = 10, height: int = 11) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    frame = b"\x2f" + struct.pack("<I", bits) + b"\x00" * 4
    return _riff(b"WEBP", _riff_chunk(b"VP8L", frame))


def webp_vp8x(width: int = 12, height: int = 13) -> bytes:
    w, h = width - 1, height - 1
    frame = b"\x00\x00\x00\x00" + w.to_bytes(3, "little") + h.to_bytes(3, "little")
    return _riff(b"WEBP", _riff_chunk(b"VP8X", frame))


SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>'
HTML = b"<!doctype html><html><body><script>alert(1)</script></body></html>"


__all__ = [
    "HTML",
    "SVG",
    "gif",
    "jpeg",
    "png",
    "webp_vp8",
    "webp_vp8l",
    "webp_vp8x",
]
