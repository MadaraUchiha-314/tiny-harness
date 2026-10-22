"""T1 (issue-38 R4.1, R4.3, R4.4): the player feeds an injected output as chunks arrive,
keeps whole frames, stops on ``stop`` and raises when the stream breaks (interrupted)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

from tests.unit.tui.fakes import FakeSpeakers, tone
from tiny_harness.interaction.tui.voice import SPEECH_FORMAT, PcmPlayer, wav_pcm


async def chunks(*parts: bytes | Exception) -> AsyncIterator[bytes]:
    for part in parts:
        await asyncio.sleep(0)
        if isinstance(part, Exception):
            raise part
        yield part


async def test_chunks_are_played_as_they_arrive_in_whole_frames() -> None:
    speakers = FakeSpeakers()
    player = PcmPlayer(open_output=speakers)
    pcm = tone(0.5, rate=24_000)
    await player.play(chunks(pcm[:1001], pcm[1001:24_000], pcm[24_000:]), SPEECH_FORMAT)
    [stream] = speakers.opened
    assert stream.fmt == SPEECH_FORMAT and stream.closed and not stream.started
    assert speakers.played == pcm
    assert all(len(block) % 2 == 0 for block in stream.written)
    assert player.played_ms == 500 and player.levels and not player.playing


async def test_stop_ends_playback() -> None:
    speakers = FakeSpeakers()
    player = PcmPlayer(open_output=speakers)
    gate = asyncio.Event()

    async def endless() -> AsyncIterator[bytes]:
        yield b"\x01\x00" * 100
        await gate.wait()
        yield b"\x01\x00" * 100

    task = asyncio.create_task(player.play(endless(), SPEECH_FORMAT))
    await asyncio.sleep(0.05)
    assert player.playing
    player.stop()
    gate.set()
    await task
    assert speakers.played == b"\x01\x00" * 100 and speakers.opened[0].closed


async def test_a_broken_stream_raises_and_closes_the_output() -> None:
    speakers = FakeSpeakers()
    player = PcmPlayer(open_output=speakers)
    broken = httpx.RemoteProtocolError("peer closed connection without sending complete body")
    with pytest.raises(httpx.RemoteProtocolError):
        await player.play(chunks(b"\x00\x01" * 10, broken), SPEECH_FORMAT)
    assert speakers.opened[0].closed and speakers.played == b"\x00\x01" * 10


def test_wav_pcm_reads_a_16_bit_wav() -> None:
    from tests.fixtures import media as fx

    pcm, fmt = wav_pcm(fx.wav(0.5))
    assert (fmt.sample_rate, fmt.channels) == (16_000, 1) and len(pcm) == 16_000
    with pytest.raises(ValueError):
        wav_pcm(b"not a wav")


async def test_a_second_play_stops_the_first_and_keeps_playing() -> None:
    """R4.3: one reply at a time. A new play stops the one running (also while its stream
    waits for bytes) before it opens the output; the old play ending later does not clear
    ``playing`` for the new one, and ``stop`` then ends the new one."""
    speakers = FakeSpeakers()
    player = PcmPlayer(open_output=speakers)
    first_gate, second_gate = asyncio.Event(), asyncio.Event()

    async def stream(sample: bytes, gate: asyncio.Event) -> AsyncIterator[bytes]:
        yield sample * 100
        await gate.wait()
        yield sample * 100

    first = asyncio.create_task(player.play(stream(b"\x01\x00", first_gate), SPEECH_FORMAT))
    await asyncio.sleep(0.05)
    second = asyncio.create_task(player.play(stream(b"\x02\x00", second_gate), SPEECH_FORMAT))
    await asyncio.sleep(0.05)
    assert first.done() and first.result().stopped
    assert speakers.opened[0].closed and speakers.opened[0].written == [b"\x01\x00" * 100]
    assert player.playing and len(speakers.opened) == 2
    first_gate.set()
    await asyncio.sleep(0.05)
    assert player.playing
    player.stop()
    await asyncio.sleep(0.05)
    assert second.done() and second.result().stopped and not player.playing
    assert speakers.played == b"\x01\x00" * 100 + b"\x02\x00" * 100
