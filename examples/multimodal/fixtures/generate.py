"""``uv run python -m examples.multimodal.fixtures.generate``: make the demo's fixtures again.

The fixtures are synthetic, so the repository holds no personal photo and no person's
voice: ``room.jpg`` comes from OpenAI image generation, and ``question.wav`` and
``followup.wav`` come from OpenAI text-to-speech. The key comes from ``OPENAI_API_KEY``
in the environment; this script never prints it. Each run costs a few cents and gives
different files.
"""

from __future__ import annotations

import array
import base64
import io
import sys
import wave
from pathlib import Path

from openai import OpenAI

HERE = Path(__file__).parent

ROOM_PROMPT = (
    "A plain photo of a small, slightly dark living room: a grey three-seat sofa against "
    "a beige wall, a wooden coffee table, one window with white curtains, a floor lamp, "
    "a rug. Eye-level view, natural light, no people, no text."
)
QUESTION = "What colour would you paint the walls to make this room feel brighter?"
FOLLOWUP = "Good idea. Please make me a mock-up image of the room with that wall colour."

PCM_RATE = 24_000  # OpenAI text-to-speech "pcm": 24 kHz, 16-bit, mono
WAV_RATE = 16_000  # what the fixtures keep: smaller, and plenty for speech


def resample(pcm: bytes, source: int = PCM_RATE, target: int = WAV_RATE) -> bytes:
    """16-bit mono PCM from ``source`` Hz to ``target`` Hz by linear interpolation."""
    samples = array.array("h", pcm)
    if sys.byteorder == "big":
        samples.byteswap()
    count = len(samples) * target // source
    out = array.array("h", bytes(2 * count))
    for i in range(count):
        position = i * source / target
        left = int(position)
        right = min(left + 1, len(samples) - 1)
        fraction = position - left
        out[i] = round(samples[left] * (1 - fraction) + samples[right] * fraction)
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def wav(pcm: bytes, rate: int = WAV_RATE) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()


def speak(client: OpenAI, text: str) -> bytes:
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts", voice="sage", input=text, response_format="pcm"
    )
    return wav(resample(response.content))


def room(client: OpenAI) -> bytes:
    result = client.images.generate(
        model="gpt-image-2",
        prompt=ROOM_PROMPT,
        size="1024x1024",
        quality="low",
        output_format="jpeg",
        output_compression=60,
    )
    data = result.data[0].b64_json if result.data else None
    if data is None:
        raise RuntimeError("the image service returned no image")
    return base64.b64decode(data)


def main() -> int:
    client = OpenAI(max_retries=0)
    (HERE / "room.jpg").write_bytes(room(client))
    (HERE / "question.wav").write_bytes(speak(client, QUESTION))
    (HERE / "followup.wav").write_bytes(speak(client, FOLLOWUP))
    for name in ("room.jpg", "question.wav", "followup.wav"):
        print(f"{name}: {(HERE / name).stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
