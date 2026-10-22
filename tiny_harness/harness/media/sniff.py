"""Content checks for untrusted media, stdlib only (issue-38 R1.4, abuse cases 2 and 7,
design critic 6).

``detect`` names a file's type from its signature, never from its name or declared type.
``image_size`` reads an image's dimensions from its header without decoding a pixel, so a
decompression bomb is refused by its declared size. ``audio_info`` walks an audio
container and counts its duration from what a decoder plays, not from a header that could
understate it: WAV data at its byte rate, every MPEG frame, every AAC access unit (MP4)
and the TOC duration of every Opus packet (Ogg, WebM). It refuses any non-audio track and
any codec it cannot count that way (critic 3).

Every parser here is bounded: it hops from header to header (frame, page, box or element)
without decoding, never descends past depth 8, and stops, refusing, as soon as the running
duration passes the cap or the hop count passes the most a capped file could need. Bytes a
walk cannot account for (beyond a 256 KiB trailing tag area after MPEG frames) refuse the
file. Every refusal is a ``SniffError`` with a ``reason``.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal

SniffReason = Literal[
    "unreadable",
    "not_audio_only",
    "audio_codec_not_accepted",
    "audio_too_long",
    "audio_duration_unknown",
]


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
_GIF_FRAMES: Final = 4096
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


def _gif_sub_blocks(raw: bytes, pos: int) -> int:
    """The position after the data sub-blocks at ``pos``, hopped by their length bytes
    without decoding; each hop moves at least one byte, so the walk ends."""
    while True:
        if pos >= len(raw):
            raise _unreadable("gif")
        length = raw[pos]
        pos += 1 + length
        if length == 0:
            return pos


def _gif_size(raw: bytes) -> tuple[int, int]:
    """The canvas every frame of the GIF covers: the logical screen widened to each image
    descriptor's ``left + width`` and ``top + height`` (critic 1). A 1x1 screen cannot hide
    a 10000x10000 frame. The walk hops extensions and LZW sub-blocks by their lengths,
    reads at most ``_GIF_FRAMES`` frames and refuses a block it does not know."""
    if len(raw) < 13:
        raise _unreadable("gif")
    width, height, packed = struct.unpack("<HHB", raw[6:11])
    pos = 13
    if packed & 0x80:
        pos += 3 << ((packed & 0x07) + 1)
    frames = 0
    while pos < len(raw):
        block = raw[pos]
        if block == 0x3B:  # trailer
            break
        if block == 0x21:  # extension: label, then sub-blocks
            pos = _gif_sub_blocks(raw, pos + 2)
        elif block == 0x2C:  # image descriptor
            frames += 1
            if frames > _GIF_FRAMES or pos + 10 > len(raw):
                raise _unreadable("gif")
            left, top, frame_width, frame_height, flags = struct.unpack(
                "<HHHHB", raw[pos + 1 : pos + 10]
            )
            width = max(width, left + frame_width)
            height = max(height, top + frame_height)
            pos += 10
            if flags & 0x80:
                pos += 3 << ((flags & 0x07) + 1)
            pos = _gif_sub_blocks(raw, pos + 1)  # LZW minimum code size, then the data
        else:
            raise _unreadable("gif")
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


# --- audio ---------------------------------------------------------------------------------

_MAX_DEPTH: Final = 8
_TRAILING_TAGS: Final = 256 * 1024
_WAV_HOPS: Final = 1024


@dataclass(frozen=True)
class AudioInfo:
    """What ``audio_info`` counted: the duration and the (single) audio codec."""

    duration_ms: int
    codec: str


def _unknown(what: str, why: str) -> SniffError:
    return SniffError("audio_duration_unknown", f"{what}: {why}")


def _not_audio(what: str, why: str) -> SniffError:
    return SniffError("not_audio_only", f"{what}: {why}")


@dataclass
class _Budget:
    """The running duration and hop count of one walk; either passing its bound refuses."""

    what: str
    max_seconds: float
    hops: int
    used: int = 0

    def hop(self, count: int = 1) -> None:
        self.used += count
        if self.used > self.hops:
            raise _unknown(self.what, "more headers than a file under the cap can hold")

    def check(self, units: int, rate: int) -> None:
        """Refuse once ``units / rate`` seconds pass the cap."""
        if units > self.max_seconds * rate:
            raise SniffError("audio_too_long", f"{self.what}: longer than {self.max_seconds} s")


def _ms(units: int, rate: int) -> int:
    return units * 1000 // rate


# WAV ----------------------------------------------------------------------------------------

_WAV_PCM: Final = 0x0001
_WAV_FLOAT: Final = 0x0003
_WAV_EXTENSIBLE: Final = 0xFFFE
_WAV_BITS: Final = frozenset({8, 16, 24, 32, 64})
_WAV_MAX_CHANNELS: Final = 32
_WAV_MAX_RATE: Final = 768_000


def _wav_byte_rate(body: bytes) -> int:
    """The byte rate of a ``fmt `` body, refused unless it is the one its sample rate,
    channels and sample size play at: a large declared rate would understate the
    duration."""
    _tag, channels, rate, byte_rate, block_align, bits = struct.unpack("<HHIIHH", body[:16])
    if not (
        1 <= channels <= _WAV_MAX_CHANNELS
        and 1 <= rate <= _WAV_MAX_RATE
        and bits in _WAV_BITS
        and block_align == channels * bits // 8
        and byte_rate == rate * block_align
    ):
        raise _unknown("wav", "the fmt chunk's byte rate is not what its format plays at")
    return byte_rate


def _wav(raw: bytes, max_seconds: float) -> AudioInfo:
    budget = _Budget("wav", max_seconds, _WAV_HOPS)
    pos = 12
    byte_rate = 0
    codec = ""
    data = 0
    while pos < len(raw):
        budget.hop()
        if pos + 8 > len(raw):
            raise _unknown("wav", "a chunk header is cut off")
        kind = raw[pos : pos + 4]
        (size,) = struct.unpack("<I", raw[pos + 4 : pos + 8])
        body = pos + 8
        if body + size > len(raw):
            raise _unknown("wav", "a chunk runs past the end of the file")
        if kind == b"fmt ":
            if size < 16:
                raise _unknown("wav", "the fmt chunk is too short")
            (tag,) = struct.unpack("<H", raw[body : body + 2])
            if tag == _WAV_EXTENSIBLE and size >= 26:
                (tag,) = struct.unpack("<H", raw[body + 24 : body + 26])
            if tag not in (_WAV_PCM, _WAV_FLOAT):
                raise _not_audio("wav", "the format is neither PCM nor IEEE float")
            byte_rate = _wav_byte_rate(raw[body : body + 16])
            codec = "pcm" if tag == _WAV_PCM else "float"
        elif kind == b"data":
            data += size
        if byte_rate:
            budget.check(data, byte_rate)
        pos = body + size + (size & 1)
    if not byte_rate or not data:
        raise _unknown("wav", "no fmt chunk, or no audio data")
    budget.check(data, byte_rate)
    return AudioInfo(duration_ms=_ms(data, byte_rate), codec=codec)


# MP3 ----------------------------------------------------------------------------------------

_MPEG_RATES: Final = {
    3: (44_100, 48_000, 32_000),
    2: (22_050, 24_000, 16_000),
    0: (11_025, 12_000, 8_000),
}
_MPEG1_KBPS: Final = {
    3: (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    2: (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
}
_MPEG2_KBPS: Final = {
    3: (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    1: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_ID3_TAGS: Final = 4
_MPEG_MIN_FRAME_MS: Final = 8  # Layer I at 48 kHz: 384 samples
_MPEG_TAGS: Final = (b"Xing", b"Info")


def _is_tag_frame(frame: bytes) -> bool:
    """A Layer III frame that carries a Xing, Info or VBRI encoder tag, not audio: a
    decoder skips it. The tag follows the side information, whose size depends on the
    version and the channel mode."""
    if (frame[1] >> 1) & 0x03 != 1:
        return False
    mono = frame[3] >> 6 == 3
    side = (17 if mono else 32) if (frame[1] >> 3) & 0x03 == 3 else (9 if mono else 17)
    return frame[4 + side : 8 + side] in _MPEG_TAGS or frame[36:40] == b"VBRI"


def _mpeg_frame(head: bytes) -> tuple[int, int, int] | None:
    """``(frame bytes, samples, sample rate)`` of the frame header ``head``, or ``None``."""
    if not _is_mpeg_frame(head):
        return None
    version = (head[1] >> 3) & 0x03
    layer = (head[1] >> 1) & 0x03  # 3 = Layer I, 2 = Layer II, 1 = Layer III
    padding = (head[2] >> 1) & 0x01
    rate = _MPEG_RATES[version][(head[2] >> 2) & 0x03]
    table = _MPEG1_KBPS if version == 3 else _MPEG2_KBPS
    bitrate = table[layer][head[2] >> 4] * 1000
    if layer == 3:
        return (12 * bitrate // rate + padding) * 4, 384, rate
    if layer == 2 or version == 3:
        return 144 * bitrate // rate + padding, 1152, rate
    return 72 * bitrate // rate + padding, 576, rate


def _mp3(raw: bytes, max_seconds: float) -> AudioInfo:
    budget = _Budget("mp3", max_seconds, int(max_seconds * 1000 / _MPEG_MIN_FRAME_MS) + 64)
    pos = 0
    for _ in range(_ID3_TAGS):
        if raw[pos : pos + 3] != b"ID3" or pos + 10 > len(raw):
            break
        size = 0
        for byte in raw[pos + 6 : pos + 10]:
            if byte & 0x80:
                raise _unknown("mp3", "the ID3 tag size is not syncsafe")
            size = (size << 7) | byte
        footer = 10 if raw[pos + 5] & 0x10 else 0
        pos += 10 + size + footer
    micros = 0  # microseconds, so frames of different rates add up exactly
    frames = 0
    skipped = False
    while pos + 4 <= len(raw):
        frame = _mpeg_frame(raw[pos : pos + 4])
        if frame is None or pos + frame[0] > len(raw):
            break
        budget.hop()
        length, samples, rate = frame
        if not frames and not skipped and _is_tag_frame(raw[pos : pos + length]):
            skipped = True
            pos += length
            continue
        micros += samples * 1_000_000 // rate
        frames += 1
        budget.check(micros, 1_000_000)
        pos += length
    if not frames:
        raise _unknown("mp3", "no MPEG audio frame")
    if len(raw) - pos > _TRAILING_TAGS:
        raise _unknown("mp3", "bytes after the frames are not a tag")
    return AudioInfo(duration_ms=micros // 1000, codec="mpeg")


# Opus ---------------------------------------------------------------------------------------

_OPUS_RATE: Final = 48_000
# The 48 kHz samples of one frame for each TOC configuration (RFC 6716, section 3.1).
_OPUS_FRAME: Final = (
    (480, 960, 1_920, 2_880) * 3  # SILK narrow-, medium- and wideband: 10, 20, 40, 60 ms
    + (480, 960) * 2  # Hybrid super-wide- and fullband: 10, 20 ms
    + (120, 240, 480, 960) * 4  # CELT: 2.5, 5, 10, 20 ms
)
_OPUS_MAX_PACKET: Final = 5_760  # 120 ms


def _opus_samples(what: str, head: bytes) -> int:
    """The 48 kHz samples one Opus packet plays, read from its TOC byte and, for a code 3
    packet, its frame count byte; ``head`` is the packet's first two bytes (or fewer)."""
    if not head:
        raise _unknown(what, "an empty Opus packet")
    toc = head[0]
    code = toc & 0x03
    if code == 0:
        frames = 1
    elif code in (1, 2):
        frames = 2
    elif len(head) < 2:
        raise _unknown(what, "an Opus packet without its frame count")
    else:
        frames = head[1] & 0x3F
    samples = _OPUS_FRAME[toc >> 3] * frames
    if not 0 < samples <= _OPUS_MAX_PACKET:
        raise _unknown(what, "an Opus packet of no frames or of more than 120 ms")
    return samples


# MP4 / M4A ----------------------------------------------------------------------------------

_MP4_CONTAINERS: Final = frozenset(
    {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"mvex", b"moof", b"traf"}
)
# The esds objectTypeIndication values of AAC: MPEG-4 audio, MPEG-2 AAC Main and LC.
_AAC_OBJECT_TYPES: Final = frozenset({0x40, 0x66, 0x67})
# Audio object types whose GASpecificConfig gives the frame length (1024 or 960).
_AAC_GENERAL: Final = frozenset({1, 2, 3, 4, 6, 7, 17, 19, 20, 21, 22, 23})
_AAC_SBR: Final = frozenset({5, 29})  # HE-AAC: the core plays its frames at the core rate
_AAC_RATES: Final = (
    96_000, 88_200, 64_000, 48_000, 44_100, 32_000, 24_000, 22_050, 16_000, 12_000, 11_025,
    8_000, 7_350,
)  # fmt: skip
_AAC_MAX_RATE: Final = 96_000
_MP4A_ENTRY_FIELDS: Final = {0: 36, 1: 52}  # sample entry version: where child boxes start


def _codec_refused(what: str, why: str) -> SniffError:
    return SniffError("audio_codec_not_accepted", f"{what}: {why}")


class _Bits:
    """A big-endian bit reader over an AAC AudioSpecificConfig."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read(self, count: int) -> int:
        if self.pos + count > len(self.data) * 8:
            raise _unknown("mp4", "the AAC decoder config is cut off")
        value = 0
        for _ in range(count):
            bit = (self.data[self.pos >> 3] >> (7 - (self.pos & 7))) & 1
            value = (value << 1) | bit
            self.pos += 1
        return value

    def object_type(self) -> int:
        kind = self.read(5)
        return 32 + self.read(6) if kind == 31 else kind

    def rate(self) -> int:
        index = self.read(4)
        if index == 15:
            return self.read(24)
        if index >= len(_AAC_RATES):
            raise _unknown("mp4", "a reserved AAC sample rate index")
        return _AAC_RATES[index]


def _aac_config(asc: bytes) -> tuple[int, int]:
    """``(sample rate, samples per frame)`` an AAC decoder plays an access unit at."""
    bits = _Bits(asc)
    kind = bits.object_type()
    rate = bits.rate()
    bits.read(4)  # channel configuration
    if kind in _AAC_SBR:
        bits.rate()  # the extension (output) rate: twice the samples at twice the rate
        kind = bits.object_type()
        if kind == 22:
            bits.read(4)
    if kind not in _AAC_GENERAL:
        raise _codec_refused("mp4", f"AAC object type {kind}")
    return rate, 960 if bits.read(1) else 1024


def _mp4_descriptor(body: bytes, at: int) -> tuple[int, int, int]:
    """``(tag, start, end)`` of the MPEG-4 descriptor at ``at``."""
    tag = body[at]
    at += 1
    size = 0
    for _ in range(4):
        byte = body[at]
        at += 1
        size = (size << 7) | (byte & 0x7F)
        if not byte & 0x80:
            break
    if at + size > len(body):
        raise _unknown("mp4", "an esds descriptor runs past its box")
    return tag, at, at + size


def _esds(body: bytes) -> tuple[int, bytes | None]:
    """``(objectTypeIndication, AudioSpecificConfig or None)`` of an ``esds`` body."""
    try:
        tag, start, end = _mp4_descriptor(body, 4)
        if tag != 0x03:
            raise _unknown("mp4", "an esds without an ES descriptor")
        flags = body[start + 2]
        at = start + 3
        at += 2 if flags & 0x80 else 0
        at += 1 + body[at] if flags & 0x40 else 0
        at += 2 if flags & 0x20 else 0
        tag, start, config_end = _mp4_descriptor(body, at)
        if tag != 0x04 or config_end > end:
            raise _unknown("mp4", "an esds without a decoder config")
        object_type = body[start]
        at = start + 13  # objectTypeIndication, streamType, buffer size and bitrates
        if at < config_end:
            tag, start, stop = _mp4_descriptor(body, at)
            if tag == 0x05 and stop <= config_end:
                return object_type, body[start:stop]
        return object_type, None
    except IndexError:
        raise _unknown("mp4", "an esds is cut off") from None


@dataclass
class _Mp4Track:
    track_id: int
    handler: bytes = b""
    codec: bytes = b""
    rate: int = 0  # the rate the decoder plays access units at
    frame: int = 1024  # samples per access unit
    units: int = 0  # access units: stsz and trun samples
    unit_bytes: int = 0
    default_size: int = 0  # trex


@dataclass
class _Mp4:
    budget: _Budget
    tracks: list[_Mp4Track] = field(default_factory=lambda: list[_Mp4Track]())
    fragment_track: int = 0
    fragment_size: int = 0  # tfhd default sample size
    payload_bytes: int = 0  # every mdat's payload

    def track(self, track_id: int) -> _Mp4Track:
        for track in self.tracks:
            if track.track_id == track_id:
                return track
        raise _unknown("mp4", f"a fragment names track {track_id}, which the file lacks")

    def add_units(self, track: _Mp4Track, units: int) -> None:
        """Count ``units`` more access units, refusing as soon as they pass the cap."""
        track.units += units
        if track.rate:
            self.budget.check(track.units * track.frame, track.rate)


def _u32(raw: bytes, at: int) -> int:
    if at + 4 > len(raw):
        raise _unknown("mp4", "a box is too short for its fields")
    return int.from_bytes(raw[at : at + 4], "big")


def _u64(raw: bytes, at: int) -> int:
    if at + 8 > len(raw):
        raise _unknown("mp4", "a box is too short for its fields")
    return int.from_bytes(raw[at : at + 8], "big")


def _mp4_sample_entry(state: _Mp4, track: _Mp4Track, body: bytes) -> None:
    """Read an ``stsd`` body: one sample entry, and for ``mp4a`` the rate and frame
    length its ``esds`` gives an AAC decoder."""
    if _u32(body, 4) != 1:
        raise _unknown("mp4", "a track without exactly one sample description")
    size = _u32(body, 8)
    entry = body[8 : 8 + size]
    if size < 36 or len(entry) < size:
        raise _unknown("mp4", "a sample entry is cut off")
    track.codec = entry[4:8]
    if track.codec != b"mp4a":
        return
    fields = _MP4A_ENTRY_FIELDS.get(int.from_bytes(entry[16:18], "big"))
    if fields is None or fields > size:
        raise _unknown("mp4", "an mp4a sample entry of an unknown version")
    track.rate = _u32(entry, 32) >> 16
    esds: bytes | None = None
    pos = fields
    while pos + 8 <= size:
        state.budget.hop()
        child = _u32(entry, pos)
        if child < 8 or pos + child > size:
            raise _unknown("mp4", "a box in the sample entry runs past it")
        if entry[pos + 4 : pos + 8] == b"esds":
            esds = entry[pos + 8 : pos + child]
        pos += child
    if esds is None:
        raise _codec_refused("mp4", "an mp4a entry without an esds")
    object_type, asc = _esds(esds)
    if object_type not in _AAC_OBJECT_TYPES:
        raise _codec_refused("mp4", f"mp4a object type 0x{object_type:02x}, not AAC")
    if asc is not None:
        track.rate, track.frame = _aac_config(asc)
    if not 0 < track.rate <= _AAC_MAX_RATE:
        raise _unknown("mp4", "an AAC track without a sample rate up to 96 kHz")


def _mp4_leaf(state: _Mp4, kind: bytes, body: bytes) -> None:
    track = state.tracks[-1] if state.tracks else None
    if kind == b"mdat":
        state.payload_bytes += len(body)
    elif track is None:
        if kind in (b"tfhd", b"trun", b"trex"):
            raise _unknown("mp4", "a fragment before any track")
        return
    elif kind == b"tkhd":
        track.track_id = _u32(body, 20 if body[:1] == b"\x01" else 12)
    elif kind == b"hdlr":
        track.handler = body[8:12]
    elif kind == b"stsd":
        _mp4_sample_entry(state, track, body)
    elif kind == b"stsz":
        _mp4_stsz(state, track, body)
    elif kind == b"trex":
        state.track(_u32(body, 4)).default_size = _u32(body, 16)
    elif kind == b"tfhd":
        flags = _u32(body, 0) & 0xFFFFFF
        state.fragment_track = _u32(body, 4)
        at = 8 + sum(width for bit, width in ((0x01, 8), (0x02, 4), (0x08, 4)) if flags & bit)
        state.fragment_size = _u32(body, at) if flags & 0x10 else 0
    elif kind == b"trun":
        _mp4_trun(state, body)


def _mp4_stsz(state: _Mp4, track: _Mp4Track, body: bytes) -> None:
    size = _u32(body, 4)
    count = _u32(body, 8)
    state.add_units(track, count)
    if size:
        track.unit_bytes += size * count
        return
    if 12 + 4 * count > len(body):
        raise _unknown("mp4", "stsz declares more samples than it holds")
    track.unit_bytes += sum(struct.unpack_from(f">{count}I", body, 12))


def _mp4_trun(state: _Mp4, body: bytes) -> None:
    track = state.track(state.fragment_track)
    flags = _u32(body, 0) & 0xFFFFFF
    count = _u32(body, 4)
    state.add_units(track, count)
    if not flags & 0x200:
        track.unit_bytes += count * (state.fragment_size or track.default_size)
        return
    at = 8 + (4 if flags & 0x001 else 0) + (4 if flags & 0x004 else 0)
    fields = sum(1 for bit in (0x100, 0x200, 0x400, 0x800) if flags & bit)
    if at + 4 * fields * count > len(body):
        raise _unknown("mp4", "trun declares more samples than it holds")
    column = 1 if flags & 0x100 else 0
    values = struct.unpack_from(f">{fields * count}I", body, at)
    track.unit_bytes += sum(values[column::fields])


def _mp4_walk(state: _Mp4, raw: bytes, start: int, end: int, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise _unknown("mp4", "boxes nest deeper than 8")
    pos = start
    while pos < end:
        state.budget.hop()
        if pos + 8 > end:
            raise _unknown("mp4", "a box header is cut off")
        size = _u32(raw, pos)
        kind = raw[pos + 4 : pos + 8]
        header = 8
        if size == 1:
            size, header = _u64(raw, pos + 8), 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise _unknown("mp4", "a box runs past its parent or the file")
        if kind in _MP4_CONTAINERS:
            if kind == b"trak":
                state.tracks.append(_Mp4Track(track_id=len(state.tracks) + 1))
            _mp4_walk(state, raw, pos + header, pos + size, depth + 1)
        else:
            _mp4_leaf(state, kind, raw[pos + header : pos + size])
        pos += size


def _mp4(raw: bytes, max_seconds: float) -> AudioInfo:
    """Count every AAC access unit (``stsz`` and ``trun`` samples) at the frame length
    and rate the decoder config gives; the ``mvhd``, ``mdhd`` and ``stts`` clocks are
    claims and do not count."""
    state = _Mp4(budget=_Budget("mp4", max_seconds, int(max_seconds * 100) + 4096))
    _mp4_walk(state, raw, 0, len(raw), 1)
    if not state.tracks:
        raise _not_audio("mp4", "no track")
    for track in state.tracks:
        if track.handler != b"soun":
            raise _not_audio("mp4", f"a {track.handler.decode('latin-1')!r} track")
        if track.codec != b"mp4a":
            raise _codec_refused("mp4", f"codec {track.codec.decode('latin-1')!r}, not AAC")
        state.budget.check(track.units * track.frame, track.rate)
    if sum(track.unit_bytes for track in state.tracks) > state.payload_bytes:
        raise _unknown("mp4", "the samples are larger than the media data")
    duration = max(_ms(track.units * track.frame, track.rate) for track in state.tracks)
    if not duration:
        raise _unknown("mp4", "no access units")
    return AudioInfo(duration_ms=duration, codec="aac")


# Ogg ----------------------------------------------------------------------------------------

_OGG_HEADER: Final = 27
_OPUS_HEAD: Final = 19  # the OpusHead packet's fixed fields
_OGG_OTHER_AUDIO: Final = (b"\x01vorbis", b"\x7fFLAC", b"Speex   ")


@dataclass
class _OggOpus:
    budget: _Budget
    packets: int = 0  # finished packets, the two headers included
    preskip: int = 0
    samples: int = 0  # 48 kHz samples of every finished audio packet

    def packet(self, head: bytes) -> None:
        """One finished packet whose first bytes are ``head``."""
        if self.packets == 0:
            if head.startswith(_OGG_OTHER_AUDIO):
                raise _codec_refused("ogg", "a codec other than Opus")
            if not head.startswith(b"OpusHead") or len(head) < _OPUS_HEAD:
                raise _not_audio("ogg", "the first packet is not an Opus id header")
            self.preskip = int.from_bytes(head[10:12], "little")
        elif self.packets == 1:
            if not head.startswith(b"OpusTags"):
                raise _unknown("ogg", "the second packet is not OpusTags")
        else:
            self.samples += _opus_samples("ogg", head[:2])
            self.budget.check(max(0, self.samples - self.preskip), _OPUS_RATE)
        self.packets += 1


def _ogg(raw: bytes, max_seconds: float) -> AudioInfo:
    """Sum the TOC duration of every Opus packet, reassembled across pages, less the
    pre-skip; a granule position past what the packets play refuses the file."""
    stream = _OggOpus(_Budget("ogg", max_seconds, 2 * int(max_seconds * 400) + 256))
    pos = 0
    serial: int | None = None
    last = 0
    head = b""  # the first bytes of the packet being reassembled
    open_packet = False
    while pos < len(raw):
        stream.budget.hop()
        if raw[pos : pos + 4] != b"OggS" or pos + _OGG_HEADER > len(raw) or raw[pos + 4] != 0:
            raise _unknown("ogg", "bytes that are not an Ogg page")
        granule, page_serial = struct.unpack("<qI", raw[pos + 6 : pos + 18])
        segments = raw[pos + 26]
        lacing = raw[pos + _OGG_HEADER : pos + _OGG_HEADER + segments]
        at = pos + _OGG_HEADER + segments
        end = at + sum(lacing)
        if len(lacing) < segments or end > len(raw):
            raise _unknown("ogg", "a page runs past the end of the file")
        if serial is None:
            serial = page_serial
        elif page_serial != serial:
            raise _not_audio("ogg", "more than one logical stream")
        if bool(raw[pos + 5] & 0x01) != open_packet:
            raise _unknown("ogg", "a page does not continue the packet before it")
        for value in lacing:
            if len(head) < _OPUS_HEAD:
                head += raw[at : at + min(value, _OPUS_HEAD - len(head))]
            at += value
            if value < 255:
                stream.packet(head)
                head = b""
        if lacing:
            open_packet = lacing[-1] == 255
        if granule != -1:
            if granule < last or granule > stream.samples:
                raise _unknown("ogg", "a granule position that is not what the packets play")
            last = granule
        pos = end
    if open_packet:
        raise _unknown("ogg", "the last packet is cut off")
    if stream.packets < 3 or stream.samples <= stream.preskip:
        raise _unknown("ogg", "no audio packet")
    return AudioInfo(duration_ms=_ms(stream.samples - stream.preskip, _OPUS_RATE), codec="opus")


# WebM ---------------------------------------------------------------------------------------

_SEGMENT: Final = 0x18538067
_TRACKS: Final = 0x1654AE6B
_CLUSTER: Final = 0x1F43B675
# Elements that may follow a Cluster at Segment level: an unknown-size Cluster ends at one.
_SEGMENT_LEVEL: Final = frozenset(
    {0x114D9B74, 0x1549A966, _TRACKS, _CLUSTER, 0x1C53BB6B, 0x1254C367, 0x1043A770, 0x1941A469}
)
_TRACK_ENTRY: Final = 0xAE
_TRACK_NUMBER: Final = 0xD7
_TRACK_TYPE: Final = 0x83
_CODEC_ID: Final = 0x86
_TRACK_AUDIO: Final = 2
_SIMPLE_BLOCK: Final = 0xA3
_BLOCK_GROUP: Final = 0xA0
_BLOCK: Final = 0xA1
_LACING_NONE, _LACING_XIPH, _LACING_FIXED, _LACING_EBML = 0, 1, 2, 3


@dataclass
class _WebM:
    raw: bytes
    budget: _Budget
    tracks: set[int] = field(default_factory=lambda: set[int]())
    samples: int = 0  # 48 kHz samples of every Opus frame

    def element(self, pos: int, end: int) -> tuple[int, int | None, int]:
        """``(id, size or None for unknown, data start)`` of the element at ``pos``."""
        self.budget.hop()
        element, pos = _ebml_id(self.raw, pos)
        size, pos = _ebml_size(self.raw, pos)
        if size is not None and pos + size > end:
            raise _unknown("webm", "an element runs past its parent or the file")
        return element, size, pos

    def children(self, start: int, end: int) -> list[tuple[int, int, int]]:
        """The ``(id, data start, data end)`` of every known-size child in ``[start, end)``."""
        out: list[tuple[int, int, int]] = []
        pos = start
        while pos < end:
            element, size, data = self.element(pos, end)
            if size is None:
                raise _unknown("webm", "an unknown size where only a known one may be")
            out.append((element, data, data + size))
            pos = data + size
        return out

    def uint(self, start: int, end: int) -> int:
        if end - start > 8:
            raise _unknown("webm", "an integer wider than 8 bytes")
        return int.from_bytes(self.raw[start:end], "big")

    def lace_sizes(self, lacing: int, count: int, at: int, end: int) -> tuple[list[int], int]:
        """The sizes of the first ``count - 1`` laced frames, and where the frames start."""
        raw = self.raw
        sizes: list[int] = []
        if lacing == _LACING_FIXED:
            if (end - at) % count:
                raise _unknown("webm", "fixed lacing that does not divide the block")
            return [(end - at) // count] * (count - 1), at
        if lacing == _LACING_XIPH:
            for _ in range(count - 1):
                size = 255
                total = 0
                while size == 255:
                    if at >= end:
                        raise _unknown("webm", "a block's lacing is cut off")
                    size = raw[at]
                    total += size
                    at += 1
                sizes.append(total)
            return sizes, at
        size, _width, at = _ebml_vint(raw, at, keep_marker=False)
        sizes.append(size)
        for _ in range(count - 2):
            value, width, at = _ebml_vint(raw, at, keep_marker=False)
            sizes.append(sizes[-1] + value - ((1 << (7 * width - 1)) - 1))
        return sizes, at

    def block(self, start: int, end: int) -> None:
        """Count every Opus frame of one SimpleBlock or Block."""
        track, _width, at = _ebml_vint(self.raw, start, keep_marker=False)
        if track not in self.tracks:
            raise _unknown("webm", f"a block of track {track}, which the file lacks")
        at += 2  # the timecode: a claim, not counted
        if at >= end:
            raise _unknown("webm", "a block is cut off")
        lacing = (self.raw[at] >> 1) & 0x03
        at += 1
        sizes: list[int] = []
        if lacing != _LACING_NONE:
            if at >= end:
                raise _unknown("webm", "a block is cut off")
            count = self.raw[at] + 1
            sizes, at = self.lace_sizes(lacing, count, at + 1, end)
        sizes.append(end - at - sum(sizes))
        if at > end or min(sizes) < 0:
            raise _unknown("webm", "a block's frames run past it")
        for size in sizes:
            self.samples += _opus_samples("webm", self.raw[at : at + min(size, 2)])
            at += size
        self.budget.check(self.samples, _OPUS_RATE)


def _webm_tracks(state: _WebM, start: int, end: int) -> None:
    for element, data, stop in state.children(start, end):
        if element != _TRACK_ENTRY:
            continue
        kind, codec, number = 0, "", 0
        for child, cdata, cstop in state.children(data, stop):
            if child == _TRACK_TYPE:
                kind = state.uint(cdata, cstop)
            elif child == _TRACK_NUMBER:
                number = state.uint(cdata, cstop)
            elif child == _CODEC_ID:
                codec = state.raw[cdata:cstop].rstrip(b"\x00").decode("ascii", "replace")
        if kind != _TRACK_AUDIO:
            raise _not_audio("webm", f"a track of type {kind}")
        if codec != "A_OPUS":
            raise _codec_refused("webm", f"codec {codec!r}, not Opus")
        if not number:
            raise _unknown("webm", "a track without a number")
        state.tracks.add(number)


def _webm_cluster(state: _WebM, start: int, end: int, *, open_ended: bool) -> int:
    """Count the frames of one Cluster's blocks; return where the Cluster ends. An
    unknown-size Cluster ends at the next Segment-level element or at ``end``."""
    pos = start
    while pos < end:
        element, size, data = state.element(pos, end)
        if open_ended and element in _SEGMENT_LEVEL:
            return pos
        if size is None:
            raise _unknown("webm", "an unknown size inside a Cluster")
        stop = data + size
        if element == _SIMPLE_BLOCK:
            state.block(data, stop)
        elif element == _BLOCK_GROUP:
            for child, cdata, cstop in state.children(data, stop):
                if child == _BLOCK:
                    state.block(cdata, cstop)
        pos = stop
    return pos


def _webm(raw: bytes, max_seconds: float) -> AudioInfo:
    """Sum the TOC duration of every Opus frame in every block of every Cluster; the
    Info Duration and the block timecodes are claims and do not count."""
    state = _WebM(raw, _Budget("webm", max_seconds, int(max_seconds * 500) + 1024))
    element, size, pos = state.element(0, len(raw))  # the EBML header
    if element != 0x1A45DFA3 or size is None:
        raise _unknown("webm", "no EBML header")
    element, size, pos = state.element(pos + size, len(raw))
    if element != _SEGMENT:
        raise _unknown("webm", "no Segment after the EBML header")
    end = len(raw) if size is None else pos + size
    if end != len(raw):
        raise _unknown("webm", "bytes after the Segment")
    while pos < end:
        element, size, data = state.element(pos, end)
        if element == _CLUSTER:
            if not state.tracks:
                raise _unknown("webm", "a Cluster before the Tracks")
            pos = _webm_cluster(
                state, data, end if size is None else data + size, open_ended=size is None
            )
            continue
        if size is None:
            raise _unknown("webm", "an unknown size outside a Cluster")
        if element == _TRACKS:
            _webm_tracks(state, data, data + size)
        pos = data + size
    if not state.tracks:
        raise _not_audio("webm", "no audio track")
    if not state.samples:
        raise _unknown("webm", "no audio frame")
    return AudioInfo(duration_ms=_ms(state.samples, _OPUS_RATE), codec="opus")


_AUDIO_WALKERS: Final[dict[str, Callable[[bytes, float], AudioInfo]]] = {
    "audio/wav": _wav,
    "audio/mpeg": _mp3,
    "audio/mp4": _mp4,
    "audio/ogg": _ogg,
    "audio/webm": _webm,
}


def audio_info(raw: bytes, media_type: str, *, max_seconds: float) -> AudioInfo:
    """Walk ``raw`` as ``media_type`` and return its counted duration; refuse a file with
    a non-audio track (``not_audio_only``), a codec other than PCM (WAV), MPEG audio
    (MP3), AAC (MP4) or Opus (Ogg, WebM) (``audio_codec_not_accepted``), one longer than
    ``max_seconds`` (``audio_too_long``) or one whose duration cannot be counted
    (``audio_duration_unknown``)."""
    walker = _AUDIO_WALKERS.get(media_type)
    if walker is None or detect(raw) != media_type:
        raise _unknown(media_type, "not a file of this type")
    return walker(raw, max_seconds)


__all__ = [
    "AudioInfo",
    "SniffError",
    "SniffReason",
    "audio_info",
    "detect",
    "image_size",
]
