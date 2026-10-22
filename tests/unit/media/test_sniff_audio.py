"""Audio duration and track checks (issue-38 R1.4, NFR size limits, design critic 6).

Every walker counts the duration from what is in the file, not from a header that could
understate it, refuses a container with any non-audio track, and stops (refusing) as soon
as the running duration passes the cap or its hop budget runs out."""

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


def test_mp3_trailing_tag_area_is_allowed() -> None:
    id3v1 = b"TAG" + b"\x00" * 125
    assert info(fx.mp3(10, trailer=id3v1), "audio/mpeg").duration_ms == 261


def test_mp4_duration_is_the_largest_of_its_clocks() -> None:
    # mvhd 1 s, mdhd 1 s, stts 47 x 1024 / 48 000 = 1.0027 s
    assert info(fx.mp4(), "audio/mp4").duration_ms == 1_002


def test_mp4_understated_header_is_overruled_by_the_samples() -> None:
    lying = fx.mp4(fx.mp4_track(duration=48, stts=((4_700, 1_024),)), duration=1)
    assert info(lying, "audio/mp4").duration_ms == 100_266


def test_fragmented_mp4_counts_the_fragments() -> None:
    # 3 fragments x 47 samples x 1024 / 48 000 Hz = 3.008 s
    assert info(fx.mp4_fragmented(3), "audio/mp4").duration_ms == 3_008


def test_ogg_opus_duration_is_the_last_granule_at_48k() -> None:
    assert info(fx.ogg((48_000, 96_000, 120_000)), "audio/ogg").duration_ms == 2_500


def test_ogg_vorbis_uses_the_id_header_rate() -> None:
    raw = fx.ogg((16_000, 24_000), codec="vorbis", rate=16_000)
    assert info(raw, "audio/ogg").duration_ms == 1_500


def test_webm_duration_from_info() -> None:
    assert info(fx.webm(duration_ms=2_000.0), "audio/webm").duration_ms == 2_000


def test_webm_without_duration_walks_the_clusters() -> None:
    raw = fx.webm(((0, (0, 20)), (1_000, (0, 480))), duration_ms=None, unknown_sizes=True)
    assert info(raw, "audio/webm").duration_ms == 1_480


def test_webm_understated_duration_is_overruled_by_the_clusters() -> None:
    raw = fx.webm(((0, (0,)), (3_000, (0, 500))), duration_ms=10.0)
    assert info(raw, "audio/webm").duration_ms == 3_500


# --- not audio only -----------------------------------------------------------------------


def test_mp4_with_video_is_refused() -> None:
    raw = fx.mp4(fx.mp4_track(), fx.mp4_track(b"vide", codec=b"avc1"))
    assert refused(raw, "audio/mp4") == "not_audio_only"


def test_mp4_with_an_unsupported_codec_is_refused() -> None:
    assert refused(fx.mp4(fx.mp4_track(codec=b"xyz1")), "audio/mp4") == "not_audio_only"


def test_webm_with_video_is_refused() -> None:
    raw = fx.webm(tracks=(fx.webm_track(), fx.webm_track(1, b"V_VP8", number=2)))
    assert refused(raw, "audio/webm") == "not_audio_only"


def test_webm_with_an_unsupported_codec_is_refused() -> None:
    raw = fx.webm(tracks=(fx.webm_track(2, b"A_WHATEVER"),))
    assert refused(raw, "audio/webm") == "not_audio_only"


def test_ogg_with_a_non_audio_stream_is_refused() -> None:
    assert refused(fx.ogg(codec="\x80theora"), "audio/ogg") == "not_audio_only"


def test_ogg_with_two_logical_streams_is_refused() -> None:
    assert refused(fx.ogg((48_000, 96_000), serials=(7, 8)), "audio/ogg") == "not_audio_only"


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


def test_mp4_whose_samples_pass_the_cap_is_refused() -> None:
    raw = fx.mp4(fx.mp4_track(duration=48, stts=((6_000, 1_024),)), duration=1)
    assert refused(raw, "audio/mp4") == "audio_too_long"


def test_ogg_with_a_lying_last_granule_is_refused() -> None:
    assert refused(fx.ogg((48_000, 96_000, 1_000)), "audio/ogg") == "audio_duration_unknown"
    assert refused(fx.ogg((48_000, 48_000 * 600)), "audio/ogg") == "audio_too_long"


def test_webm_cluster_past_the_cap_is_refused() -> None:
    raw = fx.webm(((0, (0,)), (121_000, (0,))), duration_ms=None, unknown_sizes=True)
    assert refused(raw, "audio/webm") == "audio_too_long"


def test_webm_info_duration_past_the_cap_is_refused() -> None:
    assert refused(fx.webm(duration_ms=500_000.0), "audio/webm") == "audio_too_long"


# --- indeterminate and truncated ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "media_type"),
    [
        (fx.wav(1.0)[:-100], "audio/wav"),
        (fx.wav(1.0, data_size=0xFFFFFFFF), "audio/wav"),
        (fx.wav(0.0), "audio/wav"),
        (fx.wav(1.0)[:30], "audio/wav"),
        (fx.mp4()[:-10], "audio/mp4"),
        (fx.mp4(fx.mp4_track(duration=0, stts=()), duration=0), "audio/mp4"),
        (fx.ogg()[:-5], "audio/ogg"),
        (fx.ogg(()), "audio/ogg"),
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


def test_mp4_whose_sample_tables_disagree_is_refused() -> None:
    raw = fx.mp4(fx.mp4_track(stts=((47, 1_024),), stsz=4_700))
    assert refused(raw, "audio/mp4") == "audio_duration_unknown"
    assert info(fx.mp4(fx.mp4_track(stsz=47)), "audio/mp4").duration_ms == 1_002


def test_mp4_with_tiny_sample_deltas_and_a_big_mdat_is_refused() -> None:
    """Declared clocks of a few milliseconds cannot hide a payload that takes longer
    to play even at 512 kbit/s: 128 KiB is at least 2 s."""
    track = fx.mp4_track(timescale=48_000, duration=47, stts=((47, 1),), stsz=47)
    raw = fx.mp4(track, duration=1, mdat=b"\x00" * (128 * 1024))
    assert refused(raw, "audio/mp4", cap=1.0) == "audio_too_long"
    assert info(raw, "audio/mp4", cap=CAP).duration_ms == 2_048


def test_fragmented_mp4_with_a_big_mdat_is_bounded_by_its_payload() -> None:
    raw = fx.mp4_fragmented(1, sample_duration=48)  # declares 47 ms
    raw += fx.box(b"mdat", payload=b"\x00" * (128 * 1024))
    assert refused(raw, "audio/mp4", cap=1.0) == "audio_too_long"


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
    # Pages that advance no time: the walk gives up long before reading them all.
    raw = fx.ogg((48_000,) + (-1,) * 50_000)
    assert refused(raw, "audio/ogg", cap=1.0) == "audio_duration_unknown"


def test_webm_element_budget_is_finite() -> None:
    voids = fx.ebml(0xEC, b"") * 200_000
    cluster = fx.ebml(0x1F43B675, fx.ebml(0xE7, b"\x00") + voids)
    raw = fx.webm(duration_ms=None, unknown_sizes=True) + cluster
    assert refused(raw, "audio/webm") == "audio_duration_unknown"
