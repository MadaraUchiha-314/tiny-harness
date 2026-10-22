"""Signatures and image dimensions (issue-38 R1.4, abuse cases 2 and 7): the type is read
from the bytes, never from the name or the declared type, and an image's size comes from
its header without decoding a pixel."""

from __future__ import annotations

import struct

import pytest

from tests.fixtures import media as fx
from tiny_harness.harness.media import sniff
from tiny_harness.harness.media.sniff import SniffError

# Minimal leading bytes of each audio container: enough for the signature, nothing more.
WAV_HEAD = b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt "
MP3_ID3_HEAD = b"ID3\x04\x00\x00\x00\x00\x00\x00"
MP3_FRAME_HEAD = b"\xff\xfb\x90\x64" + b"\x00" * 8
MP4_HEAD = struct.pack(">I", 20) + b"ftypM4A \x00\x00\x00\x00isom"
OGG_HEAD = b"OggS\x00\x02" + b"\x00" * 22
EBML_WEBM = bytes.fromhex("1a45dfa3") + b"\x88" + bytes.fromhex("4282") + b"\x84webm"
EBML_MKV = bytes.fromhex("1a45dfa3") + b"\x8b" + bytes.fromhex("4282") + b"\x88matroska"


@pytest.mark.parametrize(
    ("raw", "media_type"),
    [
        (fx.png(), "image/png"),
        (fx.jpeg(), "image/jpeg"),
        (fx.gif(), "image/gif"),
        (fx.gif(version=b"87a"), "image/gif"),
        (fx.webp_vp8(), "image/webp"),
        (fx.webp_vp8l(), "image/webp"),
        (fx.webp_vp8x(), "image/webp"),
        (WAV_HEAD, "audio/wav"),
        (MP3_ID3_HEAD, "audio/mpeg"),
        (MP3_FRAME_HEAD, "audio/mpeg"),
        (MP4_HEAD, "audio/mp4"),
        (OGG_HEAD, "audio/ogg"),
        (EBML_WEBM, "audio/webm"),
    ],
)
def test_detect_reads_the_type_from_the_signature(raw: bytes, media_type: str) -> None:
    assert sniff.detect(raw) == media_type


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x89PNG",
        fx.SVG,
        fx.HTML,
        b"RIFF\x00\x00\x00\x00AVI ",
        EBML_MKV,
        b"\xff\xe8\x90\x00",  # MPEG sync with a reserved version and layer
        b"\xff\xfb\x00\x00",  # MPEG free-format bitrate: no frame length to walk
        b"GIF90a" + b"\x00" * 8,
    ],
)
def test_detect_refuses_what_it_does_not_recognise(raw: bytes) -> None:
    assert sniff.detect(raw) is None


def test_rejects_html_named_png() -> None:
    assert sniff.detect(fx.HTML) != "image/png"


def test_rejects_png_declared_as_jpeg() -> None:
    assert sniff.detect(fx.png()) == "image/png"


@pytest.mark.parametrize(
    ("raw", "size"),
    [
        (fx.png(640, 480), (640, 480)),
        (fx.jpeg(1024, 768), (1024, 768)),
        (fx.jpeg(33, 44, sof=0xC2), (33, 44)),  # progressive
        (fx.gif(300, 200), (300, 200)),
        (fx.webp_vp8(1000, 500), (1000, 500)),
        (fx.webp_vp8l(16383, 2), (16383, 2)),
        (fx.webp_vp8x(16_000_000, 3), (16_000_000, 3)),
    ],
)
def test_image_size_reads_the_header(raw: bytes, size: tuple[int, int]) -> None:
    assert sniff.image_size(raw) == size


def test_rejects_huge_dimensions_without_decoding() -> None:
    bomb = fx.png(50_000, 50_000, padding=100_000)
    assert len(bomb) < 110_000
    # Only the header is read: a bomb whose image data is cut off still sizes.
    assert sniff.image_size(bomb[:40]) == (50_000, 50_000)


def test_jpeg_dht_is_not_mistaken_for_a_frame() -> None:
    dht = b"\xff\xc4" + struct.pack(">H", 5) + b"\x00\x00\x00"
    raw = fx.jpeg(9, 9)
    assert sniff.image_size(raw[:2] + dht + raw[2:]) == (9, 9)


@pytest.mark.parametrize(
    "raw",
    [
        fx.png()[:20],
        fx.png()[:8] + b"\x00\x00\x00\x0dIHDX" + b"\x00" * 13,
        b"\xff\xd8\xff\xda\x00\x02",  # scan before any frame
        b"\xff\xd8" + b"\xff\xe0\x00\x02" * 10_000,  # endless empty segments
        b"\xff\xd8\xff\xe0\xff\xff",  # segment longer than the file
        fx.gif()[:8],
        fx.webp_vp8()[:24],
        fx.HTML,
    ],
)
def test_image_size_refuses_unreadable_headers(raw: bytes) -> None:
    with pytest.raises(SniffError):
        sniff.image_size(raw)


def test_gif_size_spans_every_frame() -> None:
    frames = [fx.gif_frame(0, 0, 20, 10, data=b"\x01" * 600), fx.gif_frame(5, 3, 15, 7)]
    assert sniff.image_size(fx.animated_gif(20, 10, frames)) == (20, 10)


def test_gif_frame_larger_than_the_screen_counts() -> None:
    """A 1x1 logical screen does not hide a 10000x10000 frame (critic 1)."""
    bomb = fx.animated_gif(1, 1, [fx.gif_frame(0, 0, 10_000, 10_000)])
    assert sniff.image_size(bomb) == (10_000, 10_000)


def test_gif_frame_offset_counts_toward_the_extent() -> None:
    raw = fx.animated_gif(4, 4, [fx.gif_frame(60_000, 2, 5, 5)])
    assert sniff.image_size(raw) == (60_005, 7)


@pytest.mark.parametrize(
    "raw",
    [
        fx.animated_gif(4, 4, [fx.gif_frame(0, 0, 4, 4)])[:-12],  # descriptor cut off
        fx.animated_gif(4, 4, [b"\x99"]),  # unknown block
        fx.animated_gif(4, 4, [fx.gif_frame(0, 0, 1, 1)] * 5000),  # past the frame budget
    ],
    ids=["descriptor-cut-off", "unknown-block", "frame-budget"],
)
def test_gif_walk_refuses_what_it_cannot_account_for(raw: bytes) -> None:
    with pytest.raises(SniffError):
        sniff.image_size(raw)
