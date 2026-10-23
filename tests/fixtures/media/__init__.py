"""Small media files built in code (issue-38 T1/T8): one valid file per accepted type and
the forged ones the abuse cases need. Built rather than committed, so each test states the
header values it depends on. ``samples/`` holds real encoder output (``make.sh``) and one
Chrome MediaRecorder recording, for the duration checks to measure (critic 3)."""

from __future__ import annotations

import itertools
import struct
import zlib
from pathlib import Path
from typing import Final

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


def gif_frame(left: int, top: int, width: int, height: int, *, data: bytes = b"\x00") -> bytes:
    """One GIF frame: a graphic control extension, an image descriptor with a local colour
    table, an LZW minimum code size and ``data`` split into sub-blocks of at most 255 bytes."""
    control = b"\x21\xf9\x04\x00\x0a\x00\x00\x00"
    descriptor = b"\x2c" + struct.pack("<HHHH", left, top, width, height) + b"\x80"
    blocks = b"".join(
        bytes([len(data[i : i + 255])]) + data[i : i + 255] for i in range(0, len(data), 255)
    )
    return control + descriptor + b"\x00" * 6 + b"\x02" + blocks + b"\x00"


def animated_gif(width: int, height: int, frames: list[bytes]) -> bytes:
    """A GIF89a with a ``width`` x ``height`` logical screen, a global colour table, a
    NETSCAPE loop extension, a comment and ``frames`` (built with ``gif_frame``)."""
    screen = b"GIF89a" + struct.pack("<HH", width, height) + b"\x80\x00\x00" + b"\x00" * 6
    loop = b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    comment = b"\x21\xfe\x05hello\x00"
    return screen + loop + comment + b"".join(frames) + b"\x3b"


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


# --- audio ---------------------------------------------------------------------------------


def wav(
    seconds: float = 0.5,
    *,
    rate: int = 16_000,
    channels: int = 1,
    bits: int = 16,
    fmt_tag: int = 1,
    extra: bytes = b"",
    data_size: int | None = None,
    byte_rate: int | None = None,
    block_align: int | None = None,
) -> bytes:
    """A WAV of silence; ``extra`` is appended after the data chunk (more chunks, or junk)
    and ``data_size``, ``byte_rate`` and ``block_align`` override what the header
    declares."""
    block = channels * bits // 8
    declared_rate = rate * block if byte_rate is None else byte_rate
    declared_block = block if block_align is None else block_align
    fmt = struct.pack("<HHIIHH", fmt_tag, channels, rate, declared_rate, declared_block, bits)
    samples = b"\x00" * (int(seconds * rate) * block)
    data = b"data" + struct.pack("<I", len(samples) if data_size is None else data_size) + samples
    return _riff(b"WAVE", _riff_chunk(b"fmt ", fmt) + data + extra)


# MPEG-1 Layer III, 128 kbit/s, 44.1 kHz: 417-byte frames of 1152 samples (26.1 ms).
MP3_FRAME_128K = b"\xff\xfb\x90\x00"
# MPEG-2.5 Layer III, 8 kbit/s, 8 kHz: 72-byte frames of 576 samples (72 ms). A small file
# that plays for a long time.
MP3_FRAME_8K = b"\xff\xe3\x18\x00"


def _mp3_frame_length(header: bytes) -> int:
    return 417 if header == MP3_FRAME_128K else 72


def mp3(
    frames: int = 20,
    *,
    header: bytes = MP3_FRAME_128K,
    id3: bool = True,
    trailer: bytes = b"",
    info: bytes = b"",
) -> bytes:
    """``frames`` MPEG audio frames, behind an ID3v2 tag when ``id3``, then ``trailer``.
    ``info`` (``b"Info"``, ``b"Xing"``) makes the first frame an encoder tag frame, which
    a decoder does not play."""
    tag = b""
    if id3:
        body = b"TIT2" + struct.pack(">I", 6) + b"\x00\x00\x00title"
        size = len(body)
        syncsafe = bytes(
            [(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F]
        )
        tag = b"ID3\x04\x00\x00" + syncsafe + body
    frame = header + b"\x00" * (_mp3_frame_length(header) - 4)
    first = frame
    if info:  # MPEG-1 stereo: the tag follows 32 bytes of side information
        first = frame[:36] + info + frame[36 + len(info) :]
    return tag + (first + frame * (frames - 1) if frames else b"") + trailer


def mp3_seconds(seconds: float, *, header: bytes = MP3_FRAME_8K) -> bytes:
    per_frame = 1152 / 44_100 if header == MP3_FRAME_128K else 576 / 8_000
    return mp3(int(seconds / per_frame) + 1, header=header, id3=False)


def box(kind: bytes, *children: bytes, payload: bytes = b"") -> bytes:
    body = payload + b"".join(children)
    return struct.pack(">I", 8 + len(body)) + kind + body


def _full(kind: bytes, payload: bytes, version: int = 0) -> bytes:
    return box(kind, payload=bytes([version, 0, 0, 0]) + payload)


# AudioSpecificConfig: AAC-LC (object type 2), 48 kHz (index 3), mono, 1024-sample frames.
ASC_LC_48K: Final = bytes([0x11, 0x88])
# The same with the frame-length flag set: 960-sample frames.
ASC_LC_48K_960: Final = bytes([0x11, 0x8C])
# AAC-LC at 44.1 kHz (index 4), mono.
ASC_LC_44K: Final = bytes([0x12, 0x08])
# HE-AAC signalled explicitly: SBR (5), core 24 kHz (index 6), mono, extension 48 kHz
# (index 3), then the core object type AAC-LC (2).
ASC_HE_24K: Final = bytes([0x2B, 0x09, 0x88, 0x00])
# AAC-ELD (object type 39, escaped: 31 then 7), which plays 512-sample frames.
ASC_ELD_48K: Final = bytes([0xF8, 0xE6, 0x20])


def _descriptor(tag: int, body: bytes) -> bytes:
    return bytes([tag, len(body)]) + body


def esds(object_type: int = 0x40, asc: bytes | None = ASC_LC_48K) -> bytes:
    """An ``esds`` box: an ES descriptor whose decoder config names ``object_type`` and
    carries ``asc`` (no decoder-specific info when ``None``)."""
    specific = b"" if asc is None else _descriptor(0x05, asc)
    config = _descriptor(0x04, bytes([object_type, 0x15]) + b"\x00" * 11 + specific)
    es = _descriptor(0x03, b"\x00\x01\x00" + config + _descriptor(0x06, b"\x02"))
    return _full(b"esds", es)


def sample_entry(
    codec: bytes = b"mp4a", *, rate: int = 48_000, child: bytes | None = None
) -> bytes:
    """An audio sample entry: version 0 fields, then ``child`` (an ``esds`` for ``mp4a``
    by default)."""
    fields = b"\x00" * 6 + struct.pack(">HHH", 1, 0, 0) + b"\x00" * 4
    fields += struct.pack(">HHHHI", 1, 16, 0, 0, rate << 16)
    if child is None:
        child = esds() if codec == b"mp4a" else b""
    return box(codec, payload=fields + child)


def mp4_track(
    handler: bytes = b"soun",
    *,
    timescale: int = 48_000,
    duration: int = 48_000,
    stts: tuple[tuple[int, int], ...] = ((47, 1024),),
    codec: bytes = b"mp4a",
    entry: bytes | None = None,
    samples: int = 47,
    sample_size: int = 16,
    sizes: tuple[int, ...] | None = None,
) -> bytes:
    """A track with ``samples`` access units of ``sample_size`` bytes in its ``stsz``
    (or the per-sample ``sizes``); ``mdhd`` and ``stts`` declare what they are told,
    true or not. ``entry`` replaces the sample entry."""
    mdhd = _full(b"mdhd", struct.pack(">IIIIHH", 0, 0, timescale, duration, 0, 0))
    hdlr = _full(b"hdlr", struct.pack(">I", 0) + handler + b"\x00" * 12 + b"handler\x00")
    entries = b"".join(struct.pack(">II", count, delta) for count, delta in stts)
    stts_box = _full(b"stts", struct.pack(">I", len(stts)) + entries)
    stsd = _full(b"stsd", struct.pack(">I", 1) + (entry or sample_entry(codec)))
    if sizes is None:
        stsz = _full(b"stsz", struct.pack(">II", sample_size, samples))
    else:
        stsz = _full(
            b"stsz", struct.pack(">II", 0, len(sizes)) + struct.pack(f">{len(sizes)}I", *sizes)
        )
    stbl = box(b"stbl", stsd, stts_box, stsz)
    return box(b"trak", box(b"mdia", mdhd, hdlr, box(b"minf", stbl)))


def mp4(
    *tracks: bytes,
    timescale: int = 1_000,
    duration: int = 1_000,
    mdat: bytes = b"\x00" * 1024,
    extra: bytes = b"",
) -> bytes:
    """An MP4/M4A: ``ftyp``, ``moov`` (``mvhd`` and ``tracks``, one AAC-LC track of 47
    access units by default: 1.002 s at 48 kHz), ``mdat``, then ``extra``."""
    ftyp = box(b"ftyp", payload=b"M4A \x00\x00\x00\x00M4A isom")
    mvhd = _full(b"mvhd", struct.pack(">IIII", 0, 0, timescale, duration) + b"\x00" * 80)
    moov = box(b"moov", mvhd, *(tracks or (mp4_track(),)))
    return ftyp + moov + box(b"mdat", payload=mdat) + extra


def mp4_fragmented(
    fragments: int = 3,
    *,
    sample_duration: int = 1024,
    samples: int = 47,
    sample_size: int = 16,
    explicit_sizes: bool = False,
    mdat_size: int | None = None,
) -> bytes:
    """A fragmented MP4 as Safari's MediaRecorder writes it: an empty ``moov`` (zero
    durations, no samples) then ``moof``/``mdat`` pairs whose ``trun`` boxes hold the
    access units, sized by ``trex`` or, with ``explicit_sizes``, per sample."""
    track = mp4_track(duration=0, stts=(), samples=0)
    trex = _full(b"trex", struct.pack(">IIIII", 1, 1, sample_duration, sample_size, 0))
    ftyp = box(b"ftyp", payload=b"iso5\x00\x00\x00\x00iso5mp41")
    mvhd = _full(b"mvhd", struct.pack(">IIII", 0, 0, 1_000, 0) + b"\x00" * 80)
    moov = box(b"moov", mvhd, track, box(b"mvex", trex))
    out = ftyp + moov
    payload = samples * sample_size if mdat_size is None else mdat_size
    for _ in range(fragments):
        tfhd = box(b"tfhd", payload=bytes([0, 0, 0, 0]) + struct.pack(">I", 1))
        if explicit_sizes:
            trun_body = bytes([0, 0, 0x02, 0]) + struct.pack(">I", samples)
            trun_body += struct.pack(">I", sample_size) * samples
        else:
            trun_body = bytes([0, 0, 0, 0]) + struct.pack(">I", samples)
        trun = box(b"trun", payload=trun_body)
        out += box(b"moof", box(b"traf", tfhd, trun)) + box(b"mdat", payload=b"\x00" * payload)
    return out


# An Opus packet: TOC config 31 (CELT fullband, 20 ms), code 0 (one frame), two bytes.
OPUS_20MS: Final = bytes([0xF8, 0xFF, 0xFE])
# Config 31, code 3, a count byte of 3 frames: 60 ms.
OPUS_60MS: Final = bytes([0xFB, 0x03, 0x00, 0x00])
# Config 1 (SILK narrowband, 20 ms), code 1 (two equal frames): 40 ms.
OPUS_40MS: Final = bytes([0x09, 0x00, 0x00])
OPUS_PRESKIP: Final = 312


def opus_samples(packet: bytes) -> int:
    """The 48 kHz samples one of the packets above plays."""
    return {OPUS_20MS: 960, OPUS_60MS: 2_880, OPUS_40MS: 1_920}[packet]


def ogg_page(
    serial: int, sequence: int, granule: int, lacing: bytes, body: bytes, flags: int
) -> bytes:
    header = (
        b"OggS\x00"
        + bytes([flags])
        + struct.pack("<qIII", granule, serial, sequence, 0)
        + bytes([len(lacing)])
    )
    return header + lacing + body


def ogg(
    frames: int = 100,
    *,
    packet: bytes = OPUS_20MS,
    packets: tuple[bytes, ...] | None = None,
    codec: str = "opus",
    preskip: int = OPUS_PRESKIP,
    segments_per_page: int = 50,
    granules: dict[int, int] | None = None,
    serials: dict[int, int] | None = None,
) -> bytes:
    """An Ogg stream: the id header and comment pages, then ``frames`` copies of
    ``packet`` (or the given ``packets``) laced into pages of at most
    ``segments_per_page`` segments, so a long packet continues on the next page. Each
    audio page's granule position is the samples its finished packets play, unless
    ``granules`` (audio page index to granule) says otherwise; ``serials`` gives an
    audio page another stream serial."""
    if codec == "opus":
        head = b"OpusHead\x01\x01" + struct.pack("<HIhB", preskip, 48_000, 0, 0)
        tags = b"OpusTags" + b"\x00" * 8
    elif codec == "vorbis":
        head = b"\x01vorbis" + struct.pack("<IBI", 0, 1, 48_000) + b"\x00" * 13 + b"\x01"
        tags = b"\x03vorbis" + b"\x00" * 8
    else:
        head = codec.encode() + b"\x00" * 16
        tags = b"\x00" * 8
    audio = list(packets if packets is not None else (packet,) * frames)
    out = ogg_page(7, 0, 0, bytes([len(head)]), head, 0x02)
    out += ogg_page(7, 1, 0, bytes([len(tags)]), tags, 0x00)
    # (lacing value, bytes, the samples a packet ending on this segment plays)
    segments: list[tuple[int, bytes, int]] = []
    for item in audio:
        rest = item
        while len(rest) >= 255:
            segments.append((255, rest[:255], 0))
            rest = rest[255:]
        samples = (
            opus_samples(item)
            if codec == "opus" and item in (OPUS_20MS, OPUS_60MS, OPUS_40MS)
            else 0
        )
        segments.append((len(rest), rest, samples))
    played = 0
    index = 0
    continued = False
    while segments:
        page, segments = segments[:segments_per_page], segments[segments_per_page:]
        played += sum(samples for _, _, samples in page)
        finished = page[-1][0] < 255
        granule = played if any(value < 255 for value, _, _ in page) else -1
        if granules is not None and index in granules:
            granule = granules[index]
        flags = (0x01 if continued else 0) | (0x04 if not segments else 0)
        serial = serials.get(index, 7) if serials else 7
        lacing = bytes(value for value, _, _ in page)
        out += ogg_page(serial, index + 2, granule, lacing, b"".join(b for _, b, _ in page), flags)
        continued = not finished
        index += 1
    return out


def _vint_size(size: int | None) -> bytes:
    if size is None:
        return b"\x01\xff\xff\xff\xff\xff\xff\xff"  # unknown size
    return (
        bytes([0x08]) + size.to_bytes(4, "big")
        if size >= 2**21
        else (size | 0x200000).to_bytes(3, "big")
    )


def ebml(element: int, payload: bytes, *, unknown: bool = False) -> bytes:
    ident = element.to_bytes((element.bit_length() + 7) // 8, "big")
    return ident + _vint_size(None if unknown else len(payload)) + payload


def webm_track(track_type: int = 2, codec: bytes = b"A_OPUS", number: int = 1) -> bytes:
    return ebml(
        0xAE,
        ebml(0xD7, bytes([number])) + ebml(0x83, bytes([track_type])) + ebml(0x86, codec),
    )


def _xiph_size(size: int) -> bytes:
    return b"\xff" * (size // 255) + bytes([size % 255])


def webm_block(
    frames: tuple[bytes, ...], *, offset: int = 0, lacing: str = "", track: int = 1
) -> bytes:
    """A block body: track number, timecode ``offset``, flags, then ``frames`` (one frame
    without lacing; several with ``xiph``, ``ebml`` or ``fixed`` lacing)."""
    head = bytes([0x80 | track]) + struct.pack(">h", offset)
    if not lacing:
        (frame,) = frames
        return head + b"\x80" + frame
    count = bytes([len(frames) - 1])
    if lacing == "xiph":
        sizes = b"".join(_xiph_size(len(f)) for f in frames[:-1])
        return head + b"\x82" + count + sizes + b"".join(frames)
    if lacing == "fixed":
        return head + b"\x84" + count + b"".join(frames)
    # EBML lacing: the first size as an unsigned vint, then signed differences.
    sizes = bytes([0x80 | len(frames[0])])
    for before, after in itertools.pairwise(frames[:-1]):
        sizes += bytes([0x80 | (len(after) - len(before) + 63)])
    return head + b"\x86" + count + sizes + b"".join(frames)


def webm(
    clusters: tuple[tuple[int, int], ...] = ((0, 50), (1_000, 50)),
    *,
    frame: bytes = OPUS_20MS,
    step: int = 20,
    blocks: tuple[bytes, ...] = (),
    tracks: tuple[bytes, ...] = (),
    duration_ms: float | None = 2_000.0,
    unknown_sizes: bool = False,
    doctype: bytes = b"webm",
) -> bytes:
    """A WebM: EBML header, Segment(Info, Tracks, Cluster*). Each cluster is (timecode,
    block count): that many SimpleBlocks of ``frame``, ``step`` ms apart (TimecodeScale
    1 ms); ``blocks`` adds a last cluster of the given SimpleBlock bodies. Info carries
    ``duration_ms`` when it is not ``None``. ``unknown_sizes`` writes the Segment and the
    Clusters with unknown size and no Duration, as Chrome's MediaRecorder does."""
    header = ebml(0x1A45DFA3, ebml(0x4286, b"\x01") + ebml(0x4282, doctype))
    info_body = ebml(0x2AD7B1, (1_000_000).to_bytes(3, "big"))
    if duration_ms is not None:
        info_body += ebml(0x4489, struct.pack(">d", duration_ms))
    body = ebml(0x1549A966, info_body)
    body += ebml(0x1654AE6B, b"".join(tracks or (webm_track(),)))
    groups = [
        (timecode, [webm_block((frame,), offset=i * step) for i in range(count)])
        for timecode, count in clusters
    ]
    if blocks:
        last = groups[-1][0] + 1_000 if groups else 0
        groups.append((last, list(blocks)))
    for timecode, bodies in groups:
        cluster_body = ebml(0xE7, timecode.to_bytes(4, "big"))
        cluster_body += b"".join(ebml(0xA3, block) for block in bodies)
        body += ebml(0x1F43B675, cluster_body, unknown=unknown_sizes)
    return header + ebml(0x18538067, body, unknown=unknown_sizes)


SAMPLES: Final = Path(__file__).parent / "samples"


__all__ = [
    "ASC_ELD_48K",
    "ASC_HE_24K",
    "ASC_LC_44K",
    "ASC_LC_48K",
    "ASC_LC_48K_960",
    "HTML",
    "MP3_FRAME_8K",
    "MP3_FRAME_128K",
    "OPUS_20MS",
    "OPUS_40MS",
    "OPUS_60MS",
    "OPUS_PRESKIP",
    "SAMPLES",
    "SVG",
    "box",
    "ebml",
    "esds",
    "gif",
    "jpeg",
    "mp3",
    "mp3_seconds",
    "mp4",
    "mp4_fragmented",
    "mp4_track",
    "ogg",
    "ogg_page",
    "opus_samples",
    "png",
    "sample_entry",
    "wav",
    "webm",
    "webm_block",
    "webm_track",
    "webp_vp8",
    "webp_vp8l",
    "webp_vp8x",
]
