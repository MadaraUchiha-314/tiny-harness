"""Audio duration and track checks (issue-38 R1.4, NFR size limits, design critic 6,
critic 3).

Every walker counts the duration from what a decoder plays, not from a header that could
understate it: WAV data at its byte rate, every MPEG frame, every AAC access unit, every
Opus packet. It refuses a container with any non-audio track or a codec it cannot count,
and stops (refusing) as soon as the running duration passes the cap or its hop budget
runs out."""

from __future__ import annotations

import struct

import pytest

from tests.fixtures import media as fx
from tiny_harness.harness.media import sniff
from tiny_harness.harness.media.sniff import SniffError

CAP = 120.0


def info(raw: bytes, media_type: str, *, cap: float = CAP) -> sniff.AudioInfo:
    return sniff.audio_info(raw, media_type, max_seconds=cap)


def refused(raw: bytes, media_type: str, *, cap: float = CAP) -> str:
    with pytest.raises(SniffError) as caught:
        info(raw, media_type, cap=cap)
    return caught.value.reason


# --- a valid file per type --------------------------------------------------------------


def test_wav_duration_is_data_over_byte_rate() -> None:
    assert info(fx.wav(1.5), "audio/wav").duration_ms == 1_500
    assert info(fx.wav(0.25, rate=48_000, channels=2), "audio/wav").duration_ms == 250
    assert info(fx.wav(1.0, fmt_tag=3, bits=32), "audio/wav").duration_ms == 1_000


def test_wav_counts_every_data_chunk_and_skips_others() -> None:
    more = (
        b"LIST"
        + struct.pack("<I", 4)
        + b"INFO"
        + b"data"
        + struct.pack("<I", 16_000)
        + bytes(16_000)
    )
    assert info(fx.wav(1.0, extra=more), "audio/wav").duration_ms == 1_500


def test_mp3_duration_sums_every_frame() -> None:
    # 20 frames x 1152 samples / 44 100 Hz = 522 ms
    assert info(fx.mp3(20), "audio/mpeg").duration_ms == 522
    assert info(fx.mp3(20, id3=False), "audio/mpeg").duration_ms == 522


def test_mp3_encoder_tag_frame_is_not_counted() -> None:
    """A LAME "Info" or "Xing" frame carries no audio; a decoder skips it."""
    assert info(fx.mp3(21, info=b"Info"), "audio/mpeg").duration_ms == 522
    assert info(fx.mp3(21, info=b"Xing"), "audio/mpeg").duration_ms == 522


def test_mp3_trailing_tag_area_is_allowed() -> None:
    id3v1 = b"TAG" + b"\x00" * 125
    assert info(fx.mp3(10, trailer=id3v1), "audio/mpeg").duration_ms == 261


def test_mp4_duration_counts_the_access_units() -> None:
    # 47 AAC access units x 1024 samples / 48 000 Hz = 1.0027 s
    assert info(fx.mp4(), "audio/mp4").duration_ms == 1_002


def test_mp4_frame_length_and_rate_come_from_the_decoder_config() -> None:
    def track(asc: bytes | None, rate: int = 48_000) -> bytes:
        entry = fx.sample_entry(rate=rate, child=fx.esds(asc=asc))
        return fx.mp4(fx.mp4_track(entry=entry))

    assert info(track(fx.ASC_LC_48K_960), "audio/mp4").duration_ms == 940  # 47 x 960
    assert info(track(fx.ASC_LC_44K), "audio/mp4").duration_ms == 1_091  # at 44.1 kHz
    # HE-AAC plays 2048 samples at twice the core rate: 1024 at the core rate.
    assert info(track(fx.ASC_HE_24K), "audio/mp4").duration_ms == 2_005
    # No decoder-specific info: the sample entry's rate, 1024-sample frames.
    assert info(track(None, rate=16_000), "audio/mp4").duration_ms == 3_008


def test_mp4_per_sample_sizes_are_counted() -> None:
    raw = fx.mp4(fx.mp4_track(sizes=(10,) * 47))
    assert info(raw, "audio/mp4").duration_ms == 1_002


def test_fragmented_mp4_counts_the_fragments() -> None:
    # 3 fragments x 47 access units x 1024 / 48 000 Hz = 3.008 s
    assert info(fx.mp4_fragmented(3), "audio/mp4").duration_ms == 3_008
    assert info(fx.mp4_fragmented(3, explicit_sizes=True), "audio/mp4").duration_ms == 3_008


def test_ogg_opus_duration_sums_every_packet_less_the_pre_skip() -> None:
    # 100 packets x 20 ms - 312 samples of pre-skip
    assert info(fx.ogg(100), "audio/ogg").duration_ms == (100 * 960 - 312) * 1000 // 48_000


def test_ogg_opus_reads_each_packet_toc() -> None:
    packets = (fx.OPUS_20MS, fx.OPUS_60MS, fx.OPUS_40MS) * 10
    assert info(fx.ogg(packets=packets, preskip=0), "audio/ogg").duration_ms == 1_200


def test_ogg_packets_that_continue_on_the_next_page_count_once() -> None:
    big = fx.OPUS_20MS + b"\x00" * 600  # three segments; split over pages of two
    raw = fx.ogg(packets=(big,) * 30, segments_per_page=2, preskip=0)
    assert info(raw, "audio/ogg").duration_ms == 600


def test_webm_duration_sums_every_opus_frame() -> None:
    # 100 SimpleBlocks of one 20 ms frame
    assert info(fx.webm(), "audio/webm").duration_ms == 2_000


def test_webm_without_duration_walks_unknown_size_clusters() -> None:
    raw = fx.webm(duration_ms=None, unknown_sizes=True)
    assert info(raw, "audio/webm").duration_ms == 2_000


@pytest.mark.parametrize("lacing", ["xiph", "ebml", "fixed"])
def test_webm_laced_blocks_count_every_frame(lacing: str) -> None:
    block = fx.webm_block((fx.OPUS_20MS,) * 3, lacing=lacing)
    raw = fx.webm((), blocks=(block,) * 10, duration_ms=None)
    assert info(raw, "audio/webm").duration_ms == 600


def test_webm_block_group_blocks_count() -> None:
    group = fx.ebml(0xA0, fx.ebml(0xA1, fx.webm_block((fx.OPUS_60MS,))))
    cluster = fx.ebml(0x1F43B675, fx.ebml(0xE7, b"\x00") + group * 5)
    raw = fx.webm((), duration_ms=None, unknown_sizes=True) + cluster
    assert info(raw, "audio/webm").duration_ms == 300


# --- real encoder output ---------------------------------------------------------------------

REAL = [
    ("aac.m4a", "audio/mp4"),
    ("aac-fragmented.m4a", "audio/mp4"),
    ("mp3.mp3", "audio/mpeg"),
    ("pcm.wav", "audio/wav"),
    ("opus.ogg", "audio/ogg"),
    ("opus.webm", "audio/webm"),
    ("opus-live.webm", "audio/webm"),
    ("chrome-mediarecorder.webm", "audio/webm"),
]


@pytest.mark.parametrize(("name", "media_type"), REAL)
def test_real_samples_measure_what_a_decoder_plays(name: str, media_type: str) -> None:
    """Each sample is 1.5 s as ffmpeg decodes it (``samples/make.sh``; the Chrome one was
    recorded from the fake microphone with ``MediaRecorder``, 250 ms timeslices)."""
    raw = (fx.SAMPLES / name).read_bytes()
    assert sniff.detect(raw) == media_type
    assert abs(info(raw, media_type).duration_ms - 1_500) <= 60
    assert refused(raw, media_type, cap=1.0) == "audio_too_long"


@pytest.mark.parametrize(
    ("name", "media_type"), [("vorbis.ogg", "audio/ogg"), ("opus.mp4", "audio/mp4")]
)
def test_real_samples_in_a_codec_not_counted_are_refused(name: str, media_type: str) -> None:
    raw = (fx.SAMPLES / name).read_bytes()
    assert refused(raw, media_type) == "audio_codec_not_accepted"


# --- not audio only, or a codec not counted ---------------------------------------------------


def test_mp4_with_video_is_refused() -> None:
    raw = fx.mp4(fx.mp4_track(), fx.mp4_track(b"vide", codec=b"avc1"))
    assert refused(raw, "audio/mp4") == "not_audio_only"


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param(fx.sample_entry(b"Opus", child=fx.box(b"dOps", payload=bytes(11))), id="opus"),
        pytest.param(fx.sample_entry(b"alac"), id="alac"),
        pytest.param(fx.sample_entry(b"xyz1"), id="unknown"),
        pytest.param(fx.sample_entry(child=fx.esds(object_type=0x6B)), id="mp3-in-mp4"),
        pytest.param(fx.sample_entry(child=fx.esds(asc=fx.ASC_ELD_48K)), id="aac-eld"),
        pytest.param(fx.sample_entry(child=b""), id="mp4a-without-esds"),
    ],
)
def test_mp4_with_a_codec_other_than_aac_is_refused(entry: bytes) -> None:
    raw = fx.mp4(fx.mp4_track(entry=entry))
    assert refused(raw, "audio/mp4") == "audio_codec_not_accepted"


def test_webm_with_video_is_refused() -> None:
    raw = fx.webm(tracks=(fx.webm_track(), fx.webm_track(1, b"V_VP8", number=2)))
    assert refused(raw, "audio/webm") == "not_audio_only"


@pytest.mark.parametrize("codec", [b"A_VORBIS", b"A_WHATEVER"])
def test_webm_with_a_codec_other_than_opus_is_refused(codec: bytes) -> None:
    raw = fx.webm(tracks=(fx.webm_track(2, codec),))
    assert refused(raw, "audio/webm") == "audio_codec_not_accepted"


def test_ogg_with_a_non_audio_stream_is_refused() -> None:
    assert refused(fx.ogg(codec="\x80theora"), "audio/ogg") == "not_audio_only"


def test_ogg_vorbis_is_refused() -> None:
    assert refused(fx.ogg(codec="vorbis"), "audio/ogg") == "audio_codec_not_accepted"


def test_ogg_with_two_logical_streams_is_refused() -> None:
    assert refused(fx.ogg(serials={1: 8}), "audio/ogg") == "not_audio_only"


def test_wav_that_is_not_pcm_or_float_is_refused() -> None:
    assert refused(fx.wav(0.5, fmt_tag=0x55), "audio/wav") == "not_audio_only"


# --- over the cap --------------------------------------------------------------------------


def test_low_bitrate_mp3_over_the_cap_is_refused() -> None:
    raw = fx.mp3_seconds(121)
    assert len(raw) < 130_000  # small file, long play
    assert refused(raw, "audio/mpeg") == "audio_too_long"
    assert info(fx.mp3_seconds(100), "audio/mpeg").duration_ms > 100_000


def test_long_wav_is_refused() -> None:
    assert refused(fx.wav(3.0, rate=8_000), "audio/wav", cap=2.0) == "audio_too_long"


def test_mp4_whose_headers_understate_its_access_units_is_refused() -> None:
    """10 minutes of access units behind an mvhd, mdhd and stts that declare 1 ms."""
    units = 600 * 48_000 // 1024
    track = fx.mp4_track(duration=48, stts=((1, 48),), samples=units, sample_size=1)
    raw = fx.mp4(track, duration=1, mdat=b"\x00" * units)
    assert refused(raw, "audio/mp4") == "audio_too_long"


def test_fragmented_mp4_whose_fragments_pass_the_cap_is_refused() -> None:
    raw = fx.mp4_fragmented(60, samples=100, sample_duration=1)  # 128 s of AUs
    assert refused(raw, "audio/mp4") == "audio_too_long"


def test_ogg_whose_granule_understates_its_packets_is_refused() -> None:
    """10 minutes of packets; every granule position claims one second."""
    pages = 600 * 50 // 50
    raw = fx.ogg(600 * 50, granules=dict.fromkeys(range(pages), 48_000))
    assert refused(raw, "audio/ogg") == "audio_too_long"


def test_webm_whose_timecodes_and_duration_understate_its_frames_is_refused() -> None:
    """10 minutes of 20 ms frames, every block at timecode 0, no Duration."""
    raw = fx.webm(((0, 30_000),), step=0, duration_ms=None, unknown_sizes=True)
    assert refused(raw, "audio/webm") == "audio_too_long"


def test_webm_header_duration_does_not_count() -> None:
    """Info's Duration is a claim: the frames are what plays."""
    assert info(fx.webm(duration_ms=500_000.0), "audio/webm").duration_ms == 2_000
    assert info(fx.webm(duration_ms=10.0), "audio/webm").duration_ms == 2_000


# --- indeterminate and truncated ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "media_type"),
    [
        (fx.wav(1.0)[:-100], "audio/wav"),
        (fx.wav(1.0, data_size=0xFFFFFFFF), "audio/wav"),
        (fx.wav(0.0), "audio/wav"),
        (fx.wav(1.0)[:30], "audio/wav"),
        (fx.mp4()[:-10], "audio/mp4"),
        (fx.mp4(fx.mp4_track(samples=0)), "audio/mp4"),
        (fx.ogg()[:-5], "audio/ogg"),
        (fx.ogg(0), "audio/ogg"),
        (fx.webm()[:-3], "audio/webm"),
        (fx.webm((), duration_ms=None), "audio/webm"),
        (b"ID3\x04\x00\x00\x00\x00\x00\x0a" + b"\x00" * 10, "audio/mpeg"),
    ],
)
def test_truncated_or_empty_files_are_refused(raw: bytes, media_type: str) -> None:
    assert refused(raw, media_type) == "audio_duration_unknown"


@pytest.mark.parametrize(
    "raw",
    [
        # 1 s of samples that would "play" in 0 ms
        pytest.param(fx.wav(1.0, byte_rate=0xFFFFFFFF), id="byte-rate-max"),
        pytest.param(fx.wav(1.0, byte_rate=64_000), id="byte-rate-doubled"),
        pytest.param(fx.wav(1.0, block_align=64), id="block-align"),
        pytest.param(fx.wav(1.0, bits=12), id="bits"),
    ],
)
def test_wav_whose_rates_disagree_is_refused(raw: bytes) -> None:
    """The byte rate must be what the sample rate, channels and sample size play at:
    a header cannot understate the duration with a large byte rate."""
    assert refused(raw, "audio/wav") == "audio_duration_unknown"


def test_mp4_whose_samples_are_larger_than_its_media_data_is_refused() -> None:
    raw = fx.mp4(fx.mp4_track(samples=47, sample_size=100), mdat=b"\x00" * 1024)
    assert refused(raw, "audio/mp4") == "audio_duration_unknown"
    fragmented = fx.mp4_fragmented(2, sample_size=100, mdat_size=10)
    assert refused(fragmented, "audio/mp4") == "audio_duration_unknown"


@pytest.mark.parametrize(
    "packet",
    [
        pytest.param(b"", id="empty"),
        pytest.param(bytes([0xFB]), id="code-3-without-count"),
        pytest.param(bytes([0xFB, 0x00]), id="code-3-zero-frames"),
        pytest.param(bytes([0xFB, 0x07]), id="longer-than-120-ms"),
    ],
)
def test_ogg_packet_whose_toc_cannot_be_counted_is_refused(packet: bytes) -> None:
    raw = fx.ogg(packets=(fx.OPUS_20MS, packet, fx.OPUS_20MS))
    assert refused(raw, "audio/ogg") == "audio_duration_unknown"


def test_ogg_granule_past_what_the_packets_play_is_refused() -> None:
    raw = fx.ogg(100, granules={1: 48_000 * 600})
    assert refused(raw, "audio/ogg") == "audio_duration_unknown"


def test_ogg_granule_going_backwards_is_refused() -> None:
    raw = fx.ogg(150, granules={2: 1_000})
    assert refused(raw, "audio/ogg") == "audio_duration_unknown"


def test_webm_block_of_an_unknown_track_is_refused() -> None:
    raw = fx.webm((), blocks=(fx.webm_block((fx.OPUS_20MS,), track=5),), duration_ms=None)
    assert refused(raw, "audio/webm") == "audio_duration_unknown"


def test_unaccounted_bytes_after_the_frames_are_refused() -> None:
    junk = b"\x00" * (256 * 1024 + 1)
    assert refused(fx.mp3(10, trailer=junk), "audio/mpeg") == "audio_duration_unknown"


def test_wav_with_trailing_junk_is_refused() -> None:
    assert refused(fx.wav(0.5, extra=b"\x01\x02\x03"), "audio/wav") == "audio_duration_unknown"


def test_mp4_with_garbage_after_the_boxes_is_refused() -> None:
    raw = fx.mp4(extra=b"\xff" * 12)
    assert refused(raw, "audio/mp4") == "audio_duration_unknown"


def test_mismatched_media_type_is_refused() -> None:
    assert refused(fx.wav(1.0), "audio/ogg") == "audio_duration_unknown"
    assert refused(fx.png(), "image/png") == "audio_duration_unknown"


# --- bounded walks ---------------------------------------------------------------------------


def test_deeply_nested_mp4_boxes_stop_at_depth_eight() -> None:
    inner = fx.mp4_track()
    for _ in range(10):
        inner = fx.box(b"moov", inner)
    raw = fx.box(b"ftyp", payload=b"M4A \x00\x00\x00\x00") + inner
    assert refused(raw, "audio/mp4") in {"audio_duration_unknown", "not_audio_only"}


def test_mp4_box_budget_is_finite() -> None:
    free = fx.box(b"free") * 200_000
    assert refused(fx.mp4(extra=free), "audio/mp4") == "audio_duration_unknown"


def test_ogg_page_budget_is_finite() -> None:
    # Empty pages that advance no time: the walk gives up long before reading them all.
    empty = b"".join(fx.ogg_page(7, n + 2, -1, b"", b"", 0) for n in range(50_000))
    raw = fx.ogg(packets=()) + empty
    assert refused(raw, "audio/ogg", cap=1.0) == "audio_duration_unknown"


def test_webm_element_budget_is_finite() -> None:
    voids = fx.ebml(0xEC, b"") * 200_000
    cluster = fx.ebml(0x1F43B675, fx.ebml(0xE7, b"\x00") + voids)
    raw = fx.webm(duration_ms=None, unknown_sizes=True) + cluster
    assert refused(raw, "audio/webm") == "audio_duration_unknown"
