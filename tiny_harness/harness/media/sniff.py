"""Content checks for untrusted media, stdlib only (issue-38 R1.4, abuse cases 2 and 7,
design critic 6).

``detect`` names a file's type from its signature, never from its name or declared type.
``image_size`` reads an image's dimensions from its header without decoding a pixel, so a
decompression bomb is refused by its declared size. ``audio_info`` walks an audio
container and counts its duration from what is there, not from a header that could
understate it, and refuses any non-audio track.

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
    while pos + 4 <= len(raw):
        frame = _mpeg_frame(raw[pos : pos + 4])
        if frame is None or pos + frame[0] > len(raw):
            break
        budget.hop()
        length, samples, rate = frame
        micros += samples * 1_000_000 // rate
        frames += 1
        budget.check(micros, 1_000_000)
        pos += length
    if not frames:
        raise _unknown("mp3", "no MPEG audio frame")
    if len(raw) - pos > _TRAILING_TAGS:
        raise _unknown("mp3", "bytes after the frames are not a tag")
    return AudioInfo(duration_ms=micros // 1000, codec="mpeg")


# MP4 / M4A ----------------------------------------------------------------------------------

_MP4_CONTAINERS: Final = frozenset(
    {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"mvex", b"moof", b"traf"}
)
_MP4_AUDIO_CODECS: Final = frozenset({b"mp4a", b"Opus"})
# AAC and Opus voice stays well under this; a payload plays at least bytes * 8 / this
# seconds, whatever the sample tables declare.
_MP4_MAX_BITS_PER_SECOND: Final = 512_000


@dataclass
class _Mp4Track:
    track_id: int
    handler: bytes = b""
    codec: bytes = b""
    timescale: int = 0
    header_duration: int = 0
    samples_duration: int = 0
    default_sample_duration: int = 0
    stts_samples: int = 0
    stsz_samples: int | None = None


@dataclass
class _Mp4:
    budget: _Budget
    timescale: int = 0
    duration: int = 0
    tracks: list[_Mp4Track] = field(default_factory=lambda: list[_Mp4Track]())
    fragment_default: int = 0
    fragment_track: int = 0
    payload_bytes: int = 0  # every mdat's payload

    def track(self, track_id: int) -> _Mp4Track:
        for track in self.tracks:
            if track.track_id == track_id:
                return track
        raise _unknown("mp4", f"a fragment names track {track_id}, which the file lacks")

    def add_samples(self, track: _Mp4Track, units: int) -> None:
        track.samples_duration += units
        if track.timescale:
            self.budget.check(track.samples_duration, track.timescale)


def _u32(raw: bytes, at: int) -> int:
    if at + 4 > len(raw):
        raise _unknown("mp4", "a box is too short for its fields")
    return int.from_bytes(raw[at : at + 4], "big")


def _u64(raw: bytes, at: int) -> int:
    if at + 8 > len(raw):
        raise _unknown("mp4", "a box is too short for its fields")
    return int.from_bytes(raw[at : at + 8], "big")


def _mp4_header_clock(body: bytes) -> tuple[int, int]:
    """``(timescale, duration)`` of an ``mvhd`` or ``mdhd`` body."""
    if body[:1] == b"\x01":
        return _u32(body, 20), _u64(body, 24)
    return _u32(body, 12), _u32(body, 16)


def _mp4_leaf(state: _Mp4, kind: bytes, body: bytes) -> None:
    track = state.tracks[-1] if state.tracks else None
    if kind == b"mdat":
        state.payload_bytes += len(body)
    elif kind == b"mvhd":
        state.timescale, state.duration = _mp4_header_clock(body)
        if state.timescale:
            state.budget.check(state.duration, state.timescale)
    elif track is None:
        if kind in (b"tfhd", b"trun", b"trex"):
            raise _unknown("mp4", "a fragment before any track")
        return
    elif kind == b"tkhd":
        track.track_id = _u32(body, 20 if body[:1] == b"\x01" else 12)
    elif kind == b"mdhd":
        track.timescale, track.header_duration = _mp4_header_clock(body)
        if not track.timescale:
            raise _unknown("mp4", "a track has no timescale")
        state.budget.check(track.header_duration, track.timescale)
    elif kind == b"hdlr":
        track.handler = body[8:12]
    elif kind == b"stsd":
        track.codec = body[12:16]
    elif kind == b"stts":
        count = _u32(body, 4)
        if 8 + 8 * count > len(body):
            raise _unknown("mp4", "stts declares more entries than it holds")
        for index in range(count):
            state.budget.hop()
            samples = _u32(body, 8 + 8 * index)
            track.stts_samples += samples
            state.add_samples(track, samples * _u32(body, 12 + 8 * index))
    elif kind == b"stsz":
        track.stsz_samples = _u32(body, 8)
    elif kind == b"trex":
        state.track(_u32(body, 4)).default_sample_duration = _u32(body, 12)
    elif kind == b"tfhd":
        flags = _u32(body, 0) & 0xFFFFFF
        state.fragment_track = _u32(body, 4)
        at = 8 + (8 if flags & 0x01 else 0) + (4 if flags & 0x02 else 0)
        state.fragment_default = _u32(body, at) if flags & 0x08 else 0
    elif kind == b"trun":
        _mp4_trun(state, body)


def _mp4_trun(state: _Mp4, body: bytes) -> None:
    track = state.track(state.fragment_track)
    flags = _u32(body, 0) & 0xFFFFFF
    count = _u32(body, 4)
    at = 8 + (4 if flags & 0x001 else 0) + (4 if flags & 0x004 else 0)
    if not flags & 0x100:
        default = state.fragment_default or track.default_sample_duration
        state.add_samples(track, count * default)
        return
    stride = 4 * sum(1 for bit in (0x100, 0x200, 0x400, 0x800) if flags & bit)
    if at + stride * count > len(body):
        raise _unknown("mp4", "trun declares more samples than it holds")
    for index in range(count):
        state.budget.hop()
        state.add_samples(track, _u32(body, at + stride * index))


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
    state = _Mp4(budget=_Budget("mp4", max_seconds, int(max_seconds * 100) + 4096))
    _mp4_walk(state, raw, 0, len(raw), 1)
    if not state.tracks:
        raise _not_audio("mp4", "no track")
    for track in state.tracks:
        if track.handler != b"soun":
            raise _not_audio("mp4", f"a {track.handler.decode('latin-1')!r} track")
        if track.codec not in _MP4_AUDIO_CODECS:
            raise _not_audio("mp4", f"unsupported codec {track.codec.decode('latin-1')!r}")
        if track.stsz_samples is not None and track.stsz_samples != track.stts_samples:
            raise _unknown("mp4", "stts and stsz count different samples")
    # The payload bounds the duration from below: tiny sample deltas cannot hide it.
    payload_bits = state.payload_bytes * 8
    state.budget.check(payload_bits, _MP4_MAX_BITS_PER_SECOND)
    durations = [_ms(state.duration, state.timescale)] if state.timescale else []
    for track in state.tracks:
        longest = max(track.header_duration, track.samples_duration)
        durations.append(_ms(longest, track.timescale))
    declared = max(durations)
    if not declared:
        raise _unknown("mp4", "no duration and no samples")
    duration = max(declared, _ms(payload_bits, _MP4_MAX_BITS_PER_SECOND))
    return AudioInfo(duration_ms=duration, codec=state.tracks[0].codec.decode("latin-1"))


# Ogg ----------------------------------------------------------------------------------------

_OGG_HEADER: Final = 27
_OPUS_RATE: Final = 48_000


def _ogg_codec(packet: bytes) -> tuple[str, int]:
    if packet.startswith(b"OpusHead"):
        return "opus", _OPUS_RATE
    if packet.startswith(b"\x01vorbis") and len(packet) >= 16:
        (rate,) = struct.unpack("<I", packet[12:16])
        if rate:
            return "vorbis", rate
    raise _not_audio("ogg", "the first packet is neither OpusHead nor a vorbis id header")


def _ogg(raw: bytes, max_seconds: float) -> AudioInfo:
    budget = _Budget("ogg", max_seconds, int(max_seconds * 1000) + 64)
    pos = 0
    serial: int | None = None
    codec, rate = "", 0
    last = 0
    while pos < len(raw):
        budget.hop()
        if raw[pos : pos + 4] != b"OggS" or pos + _OGG_HEADER > len(raw) or raw[pos + 4] != 0:
            raise _unknown("ogg", "bytes that are not an Ogg page")
        granule, page_serial = struct.unpack("<qI", raw[pos + 6 : pos + 18])
        segments = raw[pos + 26]
        lacing = raw[pos + _OGG_HEADER : pos + _OGG_HEADER + segments]
        body = pos + _OGG_HEADER + segments
        end = body + sum(lacing)
        if len(lacing) < segments or end > len(raw):
            raise _unknown("ogg", "a page runs past the end of the file")
        if serial is None:
            serial = page_serial
            codec, rate = _ogg_codec(raw[body:end])
        elif page_serial != serial:
            raise _not_audio("ogg", "more than one logical stream")
        if granule != -1:
            if granule < last:
                raise _unknown("ogg", "granule positions go backwards")
            last = granule
            budget.check(last, rate)
        pos = end
    if not last:
        raise _unknown("ogg", "no audio page")
    return AudioInfo(duration_ms=_ms(last, rate), codec=codec)


# WebM ---------------------------------------------------------------------------------------

_SEGMENT: Final = 0x18538067
_INFO: Final = 0x1549A966
_TRACKS: Final = 0x1654AE6B
_CLUSTER: Final = 0x1F43B675
# Elements that may follow a Cluster at Segment level: an unknown-size Cluster ends at one.
_SEGMENT_LEVEL: Final = frozenset(
    {0x114D9B74, _INFO, _TRACKS, _CLUSTER, 0x1C53BB6B, 0x1254C367, 0x1043A770, 0x1941A469}
)
_TIMECODE_SCALE: Final = 0x2AD7B1
_DURATION: Final = 0x4489
_TRACK_ENTRY: Final = 0xAE
_TRACK_TYPE: Final = 0x83
_CODEC_ID: Final = 0x86
_TRACK_AUDIO: Final = 2
_WEBM_AUDIO_CODECS: Final = frozenset({"A_OPUS", "A_VORBIS"})
_CLUSTER_TIMECODE: Final = 0xE7
_SIMPLE_BLOCK: Final = 0xA3
_BLOCK_GROUP: Final = 0xA0
_BLOCK: Final = 0xA1
_NS_PER_MS: Final = 1_000_000


@dataclass
class _WebM:
    raw: bytes
    budget: _Budget
    scale: int = _NS_PER_MS
    header_duration: float = 0.0
    codecs: list[str] = field(default_factory=lambda: list[str]())
    latest: int = 0  # the latest block time seen, in timecode units

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

    def block_time(self, cluster_time: int, start: int, end: int) -> None:
        _track, _width, at = _ebml_vint(self.raw, start, keep_marker=False)
        if at + 2 > end:
            raise _unknown("webm", "a block is cut off")
        (offset,) = struct.unpack(">h", self.raw[at : at + 2])
        self.latest = max(self.latest, cluster_time + offset)
        self.budget.check(self.latest * self.scale, 1_000_000_000)


def _webm_info(state: _WebM, start: int, end: int) -> None:
    duration: bytes | None = None
    for element, data, stop in state.children(start, end):
        if element == _TIMECODE_SCALE:
            state.scale = state.uint(data, stop)
        elif element == _DURATION:
            duration = state.raw[data:stop]
    if not state.scale:
        raise _unknown("webm", "a zero timecode scale")
    if duration is not None:
        if len(duration) not in (4, 8):
            raise _unknown("webm", "a Duration that is not a float")
        (value,) = struct.unpack(">f" if len(duration) == 4 else ">d", duration)
        if not value >= 0:  # NaN too
            raise _unknown("webm", "a negative Duration")
        state.header_duration = value
        state.budget.check(int(value * state.scale), 1_000_000_000)


def _webm_tracks(state: _WebM, start: int, end: int) -> None:
    for element, data, stop in state.children(start, end):
        if element != _TRACK_ENTRY:
            continue
        kind, codec = 0, ""
        for child, cdata, cstop in state.children(data, stop):
            if child == _TRACK_TYPE:
                kind = state.uint(cdata, cstop)
            elif child == _CODEC_ID:
                codec = state.raw[cdata:cstop].rstrip(b"\x00").decode("ascii", "replace")
        if kind != _TRACK_AUDIO:
            raise _not_audio("webm", f"a track of type {kind}")
        if codec not in _WEBM_AUDIO_CODECS:
            raise _not_audio("webm", f"unsupported codec {codec!r}")
        state.codecs.append(codec)


def _webm_cluster(state: _WebM, start: int, end: int, *, open_ended: bool) -> int:
    """Walk one Cluster's children; return where the Cluster ends. An unknown-size Cluster
    ends at the next Segment-level element or at ``end``."""
    pos = start
    time = 0
    while pos < end:
        element, size, data = state.element(pos, end)
        if open_ended and element in _SEGMENT_LEVEL:
            return pos
        if size is None:
            raise _unknown("webm", "an unknown size inside a Cluster")
        stop = data + size
        if element == _CLUSTER_TIMECODE:
            time = state.uint(data, stop)
        elif element == _SIMPLE_BLOCK:
            state.block_time(time, data, stop)
        elif element == _BLOCK_GROUP:
            for child, cdata, cstop in state.children(data, stop):
                if child == _BLOCK:
                    state.block_time(time, cdata, cstop)
        pos = stop
    return pos


def _webm(raw: bytes, max_seconds: float) -> AudioInfo:
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
    clusters = 0
    while pos < end:
        element, size, data = state.element(pos, end)
        if element == _CLUSTER:
            clusters += 1
            pos = _webm_cluster(
                state, data, end if size is None else data + size, open_ended=size is None
            )
            continue
        if size is None:
            raise _unknown("webm", "an unknown size outside a Cluster")
        if element == _INFO:
            _webm_info(state, data, data + size)
        elif element == _TRACKS:
            _webm_tracks(state, data, data + size)
        pos = data + size
    if not state.codecs:
        raise _not_audio("webm", "no audio track")
    duration_ns = max(int(state.header_duration * state.scale), state.latest * state.scale)
    if not clusters or not duration_ns:
        raise _unknown("webm", "no audio cluster")
    return AudioInfo(duration_ms=duration_ns // _NS_PER_MS, codec=state.codecs[0])


_AUDIO_WALKERS: Final[dict[str, Callable[[bytes, float], AudioInfo]]] = {
    "audio/wav": _wav,
    "audio/mpeg": _mp3,
    "audio/mp4": _mp4,
    "audio/ogg": _ogg,
    "audio/webm": _webm,
}


def audio_info(raw: bytes, media_type: str, *, max_seconds: float) -> AudioInfo:
    """Walk ``raw`` as ``media_type`` and return its counted duration; refuse a file with
    a non-audio track or an unsupported codec (``not_audio_only``), one longer than
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
