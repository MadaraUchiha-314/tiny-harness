"""Fake audio devices for the voice tests: nothing here opens a microphone or speakers."""

from __future__ import annotations

import math
import struct
from collections.abc import Callable

from tiny_harness.harness.media import AudioFormat


def tone(seconds: float, *, rate: int = 16_000, amplitude: int = 8000) -> bytes:
    """A 440 Hz tone: loud enough not to count as silence."""
    count = int(seconds * rate)
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(count)
    )


def silence(seconds: float, *, rate: int = 16_000) -> bytes:
    return b"\x00\x00" * int(seconds * rate)


class FakeInput:
    """A microphone: ``feed`` delivers blocks as the device callback would."""

    def __init__(self, rate: int, on_audio: Callable[[bytes], None]) -> None:
        self.rate = rate
        self.on_audio = on_audio
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True

    def feed(self, pcm: bytes, block: int = 3200) -> None:
        for at in range(0, len(pcm), block):
            self.on_audio(pcm[at : at + block])


class FakeMicrophone:
    """The ``open_input`` factory; ``opened`` keeps every stream it opened."""

    def __init__(self) -> None:
        self.opened: list[FakeInput] = []

    def __call__(self, rate: int, on_audio: Callable[[bytes], None]) -> FakeInput:
        stream = FakeInput(rate, on_audio)
        self.opened.append(stream)
        return stream

    @property
    def stream(self) -> FakeInput:
        return self.opened[-1]


class FakeOutput:
    def __init__(self, fmt: AudioFormat) -> None:
        self.fmt = fmt
        self.written: list[bytes] = []
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def write(self, data: bytes) -> None:
        self.written.append(data)

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class FakeSpeakers:
    """The ``open_output`` factory."""

    def __init__(self) -> None:
        self.opened: list[FakeOutput] = []

    def __call__(self, fmt: AudioFormat) -> FakeOutput:
        stream = FakeOutput(fmt)
        self.opened.append(stream)
        return stream

    @property
    def played(self) -> bytes:
        return b"".join(b"".join(s.written) for s in self.opened)
