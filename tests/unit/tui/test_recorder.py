"""T1 (issue-38 R3.3, R3.6): the recorder on an injected microphone: 16 kHz mono 16-bit
WAV out; shorter than 0.3 s or silent is discarded; the microphone is closed after each
recording."""

from __future__ import annotations

import io
import wave

import pytest

from tests.unit.tui.fakes import FakeMicrophone, silence, tone
from tiny_harness.interaction.tui.voice import (
    INPUT_UNAVAILABLE,
    Recorder,
    VoiceUnavailable,
    open_sounddevice_input,
)


def test_a_recording_is_a_16_khz_mono_wav() -> None:
    mic = FakeMicrophone()
    recorder = Recorder(open_input=mic)
    recorder.start()
    assert mic.stream.started and mic.stream.rate == 16_000 and recorder.recording
    pcm = tone(1.5)
    mic.stream.feed(pcm)
    assert recorder.duration_ms == 1500
    assert 0 < recorder.level <= 1 and recorder.levels
    wav = recorder.stop()
    assert wav is not None and mic.stream.closed and not recorder.recording
    with wave.open(io.BytesIO(wav)) as reader:
        assert (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) == (
            16_000,
            1,
            2,
        )
        assert reader.readframes(reader.getnframes()) == pcm
    assert recorder.duration_ms == 1500  # kept for the part's durationMs


def test_short_or_silent_recordings_are_discarded() -> None:
    mic = FakeMicrophone()
    recorder = Recorder(open_input=mic)
    recorder.start()
    mic.stream.feed(tone(0.25))
    assert recorder.stop() is None
    recorder.start()
    mic.stream.feed(silence(2.0))
    assert recorder.stop() is None
    assert all(s.closed for s in mic.opened) and len(mic.opened) == 2


def test_capture_stops_at_the_cap_and_discard_closes_the_microphone() -> None:
    mic = FakeMicrophone()
    recorder = Recorder(open_input=mic, max_seconds=1.0)
    recorder.start()
    mic.stream.feed(tone(1.5))
    assert recorder.duration_ms == 1000
    recorder.discard()
    assert mic.stream.closed and not recorder.recording


def test_without_portaudio_the_reason_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    real = importlib.import_module

    def no_portaudio(name: str, package: str | None = None) -> object:
        if name == "sounddevice":
            raise OSError("PortAudio library not found")
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", no_portaudio)
    recorder = Recorder(open_input=open_sounddevice_input)
    with pytest.raises(VoiceUnavailable, match=r"install tiny-harness\[voice\] \(PortAudio\)"):
        recorder.start()
    assert str(VoiceUnavailable(INPUT_UNAVAILABLE)) == INPUT_UNAVAILABLE
    assert not recorder.recording
