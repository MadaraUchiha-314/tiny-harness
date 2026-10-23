"""Voice in the TUI (issue-38 R3, R4, R8): hold-to-talk detection, recording and playback.

``HoldDetector`` is pure: it turns Space key events, with the times they came, into a
typed space, the start of a hold or its end, so its timing is tested with a fake clock.
``Recorder`` captures 16 kHz mono 16-bit audio and returns it as a WAV (stdlib ``wave``),
or nothing for a recording shorter than 0.3 s or silent. ``PcmPlayer`` plays raw PCM as
it arrives. Both open their device through a factory, so tests inject fakes and nothing
here needs a microphone or speakers; the default factories use ``sounddevice``
(PortAudio, the ``voice`` extra). The microphone is open only between ``start`` and
``stop`` (security design (d)).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import io
import math
import time
import wave
from array import array
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from types import ModuleType
from typing import Final, Literal, Protocol, cast

from tiny_harness.harness.media import AudioFormat

INPUT_UNAVAILABLE: Final = "voice input unavailable: install tiny-harness[voice] (PortAudio)"
OUTPUT_UNAVAILABLE: Final = "voice output unavailable: install tiny-harness[voice] (PortAudio)"
RECORD_RATE: Final = 16_000
MIN_SECONDS: Final = 0.3
SILENCE_RMS: Final = 0.005  # of full scale: below this the recording is discarded (R3.6)
FULL_SCALE: Final = 32768.0
METER: Final = "▁▂▃▄▅▆▇█"
SPEECH_FORMAT: Final = AudioFormat(encoding="pcm_s16le", sample_rate=24_000, channels=1)


class VoiceUnavailable(RuntimeError):
    """No ``sounddevice``, no PortAudio, or no device: the reason is the message."""


def sounddevice() -> ModuleType:
    """The ``sounddevice`` module; importing it loads PortAudio, so a missing library is
    an ``OSError`` there."""
    try:
        # By name, not a static import: the ``voice`` extra is optional, so a type check
        # of an install without it must not need the module.
        return importlib.import_module("sounddevice")
    except (ImportError, OSError) as exc:
        raise VoiceUnavailable(INPUT_UNAVAILABLE) from exc


def meter(levels: list[float], width: int = 12) -> str:
    """The newest ``width`` levels (0..1) as block characters; at rest, a flat line."""
    shown = levels[-width:] or [0.0] * width
    top = len(METER) - 1
    return "".join(METER[min(top, max(0, round(level * top)))] for level in shown)


def rms(pcm: bytes) -> float:
    """Root mean square of 16-bit little-endian samples, as a fraction of full scale."""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / FULL_SCALE


# --- hold to talk --------------------------------------------------------------------------

type HoldEvent = Literal["hold", "start", "repeat"]


class HoldDetector:
    """Turns a stream of Space key events into press / hold-start / hold-end.
    A first Space on an empty composer is held back. A second Space within
    ``repeat_window`` (default 0.6 s, ``--hold-ms``) is auto-repeat: hold starts. Each
    further Space resets a ``release_gap`` timer (0.25 s); its expiry is the release. A
    lone Space whose window expires is typed as a space. WHERE Textual delivers
    key-release events (kitty keyboard protocol), the release event ends the hold at
    once.

    Call ``tick`` before ``key_down`` and on a timer: it reports what time alone decides."""

    def __init__(
        self,
        *,
        repeat_window: float = 0.6,
        release_gap: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repeat_window = repeat_window
        self.release_gap = release_gap
        self.clock = clock
        self.state: Literal["idle", "pending", "tapped", "holding"] = "idle"
        self._first = 0.0
        self._last = 0.0

    @property
    def active(self) -> bool:
        """A Space is held back or held down: the caller should keep ticking."""
        return self.state != "idle"

    def key_down(self, now: float) -> HoldEvent:
        if self.state == "holding":
            self._last = now
            return "repeat"
        if self.state == "pending" and now - self._first <= self.repeat_window:
            self.state, self._last = "holding", now
            return "start"
        # idle (or a tap whose space the caller has not ticked out yet): hold it back
        self.state, self._first = "pending", now
        return "hold"

    def key_up(self, now: float) -> Literal["end"] | None:
        if self.state == "holding":
            self.state = "idle"
            return "end"
        if self.state == "pending":  # released before any repeat: a tap, typed at once
            self.state = "tapped"
        return None

    def tick(self, now: float) -> Literal["type-space", "end"] | None:
        if self.state == "tapped" or (
            self.state == "pending" and now - self._first > self.repeat_window
        ):
            self.state = "idle"
            return "type-space"
        if self.state == "holding" and now - self._last > self.release_gap:
            self.state = "idle"
            return "end"
        return None


# --- recording -----------------------------------------------------------------------------


class InputStream(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


type OpenInput = Callable[[int, Callable[[bytes], None]], InputStream]
"""Opens a 16-bit mono input at the given rate that calls back with each block's bytes."""


def open_sounddevice_input(rate: int, on_audio: Callable[[bytes], None]) -> InputStream:
    module = sounddevice()

    def callback(data: object, frames: int, when: object, status: object) -> None:
        on_audio(bytes(cast(bytes, data)))

    try:
        stream = module.RawInputStream(
            samplerate=rate, channels=1, dtype="int16", callback=callback
        )
    except Exception as exc:  # PortAudioError: no device, or it is busy
        raise VoiceUnavailable(f"voice input unavailable: {exc}") from exc
    return cast(InputStream, stream)


class Recorder:
    """``start`` opens the microphone, ``stop`` closes it and returns the WAV, or ``None``
    when the recording is shorter than ``min_seconds`` or silent (R3.6). ``level`` (0..1)
    and ``levels`` drive the recording meter, ``duration_ms`` the timer (it keeps the last
    recording's length after ``stop``); at ``max_seconds`` capture stops."""

    def __init__(
        self,
        *,
        open_input: OpenInput = open_sounddevice_input,
        rate: int = RECORD_RATE,
        min_seconds: float = MIN_SECONDS,
        max_seconds: float = 120.0,
        silence: float = SILENCE_RMS,
    ) -> None:
        self.open_input = open_input
        self.rate = rate
        self.min_seconds = min_seconds
        self.max_bytes = int(max_seconds * rate) * 2
        self.silence = silence
        self.level = 0.0
        self.levels: list[float] = []
        self._chunks: list[bytes] = []
        self._size = 0
        self._stream: InputStream | None = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def duration_ms(self) -> int:
        return self._size * 1000 // (self.rate * 2)

    def start(self) -> None:
        """Open the microphone; ``VoiceUnavailable`` names why it cannot be."""
        if self._stream is not None:
            return
        self._chunks, self._size, self.level, self.levels = [], 0, 0.0, []
        stream = self.open_input(self.rate, self._on_audio)
        try:
            stream.start()
        except Exception as exc:  # PortAudioError: the device went away, or it is busy
            with contextlib.suppress(Exception):  # the start's error is the one to report
                stream.close()
            raise VoiceUnavailable(f"voice input unavailable: {exc}") from exc
        self._stream = stream

    def _on_audio(self, data: bytes) -> None:
        if self._size >= self.max_bytes:
            return
        data = data[: self.max_bytes - self._size]
        self._chunks.append(data)
        self._size += len(data)
        self.level = min(1.0, rms(data) * 4)  # speech sits well below full scale
        self.levels.append(self.level)

    def discard(self) -> None:
        self._close()
        self._chunks, self._size = [], 0

    def stop(self) -> bytes | None:
        self._close()
        pcm = b"".join(self._chunks)
        self._chunks = []
        if len(pcm) < self.min_seconds * self.rate * 2 or rms(pcm) < self.silence:
            return None
        out = io.BytesIO()
        with wave.open(out, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(self.rate)
            writer.writeframes(pcm)
        return out.getvalue()

    def _close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()


# --- playback ------------------------------------------------------------------------------


class OutputStream(Protocol):
    def start(self) -> None: ...

    def write(self, data: bytes) -> object: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


type OpenOutput = Callable[[AudioFormat], OutputStream]


def open_sounddevice_output(fmt: AudioFormat) -> OutputStream:
    try:
        module = sounddevice()
    except VoiceUnavailable as exc:
        raise VoiceUnavailable(OUTPUT_UNAVAILABLE) from exc
    try:
        stream = module.RawOutputStream(
            samplerate=fmt.sample_rate, channels=fmt.channels, dtype="int16"
        )
    except Exception as exc:  # PortAudioError: no device, or it is busy
        raise VoiceUnavailable(f"voice output unavailable: {exc}") from exc
    return cast(OutputStream, stream)


@dataclass(frozen=True, slots=True)
class Played:
    """How one ``PcmPlayer.play`` ended: what it played, and whether it was stopped
    (by ``stop`` or by a newer ``play``) before its stream ended."""

    played_ms: int
    stopped: bool


class PcmPlayer:
    """Plays 16-bit PCM from an async byte stream as it arrives, in blocks of 100 ms (so
    ``stop`` takes effect within one block and ``levels`` moves with the voice); ``stop``
    ends it, also while the stream waits for bytes. One play at a time: a new ``play``
    stops the running one and waits for it to close its output first. A stream that
    breaks raises from ``play`` (the caller shows "interrupted")."""

    def __init__(self, *, open_output: OpenOutput = open_sounddevice_output) -> None:
        self.open_output = open_output
        self.levels: list[float] = []
        self.played_ms = 0
        self.stopped = False
        self.playing = False
        self._interrupt = asyncio.Event()  # set: the current play stops
        self._finished: asyncio.Event | None = None  # set when the current play ended

    async def play(self, chunks: AsyncIterator[bytes], fmt: AudioFormat) -> Played:
        previous = self._finished
        self._interrupt.set()
        interrupt, finished = asyncio.Event(), asyncio.Event()
        self._interrupt, self._finished = interrupt, finished
        try:
            if previous is not None:
                await previous.wait()
            if interrupt.is_set():  # a newer play (or stop) came while this one waited
                return Played(0, stopped=True)
            return await self._play(chunks, fmt, interrupt)
        finally:
            if self._interrupt is interrupt:  # no newer play: nothing plays now
                self.playing = False
            finished.set()

    async def _play(
        self, chunks: AsyncIterator[bytes], fmt: AudioFormat, interrupt: asyncio.Event
    ) -> Played:
        self.levels, self.played_ms, self.stopped = [], 0, False
        frame = 2 * fmt.channels
        rate = fmt.sample_rate * frame
        block_size = max(frame, rate // 10 // frame * frame)
        stream = self.open_output(fmt)
        stream.start()
        self.playing = True
        carry = b""
        written = 0
        played_ms = 0
        iterator = aiter(chunks)
        try:
            while not interrupt.is_set():
                chunk = await self._next(iterator, interrupt)
                if chunk is None:
                    break
                data = carry + chunk
                usable = len(data) - len(data) % frame
                carry = data[usable:]
                for at in range(0, usable, block_size):
                    if interrupt.is_set():
                        break
                    block = data[at : min(at + block_size, usable)]
                    level = min(1.0, rms(block) * 4)
                    await asyncio.to_thread(stream.write, block)
                    written += len(block)
                    played_ms = written * 1000 // rate
                    if self._interrupt is interrupt:  # the meter shows the current play
                        self.levels.append(level)
                        self.played_ms = played_ms
        finally:
            stream.stop()
            stream.close()
            if self._interrupt is interrupt:  # a newer play owns ``playing`` now
                self.playing = False
                self.stopped = interrupt.is_set()
        return Played(played_ms, stopped=interrupt.is_set())

    @staticmethod
    async def _next(iterator: AsyncIterator[bytes], interrupt: asyncio.Event) -> bytes | None:
        """The stream's next chunk, or ``None`` at its end or once ``interrupt`` is set
        (the pending read is cancelled)."""
        read = asyncio.ensure_future(anext(iterator))
        halt = asyncio.ensure_future(interrupt.wait())
        try:
            await asyncio.wait((read, halt), return_when=asyncio.FIRST_COMPLETED)
        finally:
            halt.cancel()
            if not read.done():
                read.cancel()
                await asyncio.gather(read, return_exceptions=True)
        if not read.done() or read.cancelled():
            return None
        try:
            return read.result()
        except StopAsyncIteration:
            return None

    def stop(self) -> None:
        self.stopped = True
        self._interrupt.set()


def wav_pcm(data: bytes) -> tuple[bytes, AudioFormat]:
    """A 16-bit PCM WAV's samples and format; ``ValueError`` for anything else."""
    try:
        with wave.open(io.BytesIO(data), "rb") as reader:
            if reader.getsampwidth() != 2:
                raise ValueError("only 16-bit WAV plays here")
            fmt = AudioFormat(
                encoding="pcm_s16le",
                sample_rate=reader.getframerate(),
                channels=reader.getnchannels(),
            )
            return reader.readframes(reader.getnframes()), fmt
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"not a playable WAV: {exc}") from exc


async def once(data: bytes) -> AsyncIterator[bytes]:
    yield data


__all__ = [
    "INPUT_UNAVAILABLE",
    "OUTPUT_UNAVAILABLE",
    "SPEECH_FORMAT",
    "HoldDetector",
    "HoldEvent",
    "InputStream",
    "OpenInput",
    "OpenOutput",
    "OutputStream",
    "PcmPlayer",
    "Played",
    "Recorder",
    "VoiceUnavailable",
    "meter",
    "once",
    "open_sounddevice_input",
    "open_sounddevice_output",
    "rms",
    "sounddevice",
    "wav_pcm",
]
