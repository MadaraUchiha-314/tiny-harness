"""Feature: The multi-modal demo
Requirement: docs/specs/issue-38/requirements.md#R7

``examples/multimodal`` on an embedded Temporal with OpenAI for the model, speech-to-text,
text-to-speech and images, driven through the A2A client with the demo's committed
fixtures: a photo, an audio file, a voice turn with a spoken reply read through the media
route, a generated image, and a turn that refers back to the first photo. The model's
words differ from run to run, so the test asserts structure, not wording.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import time
import uuid
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import httpx
import pytest
import pytest_asyncio
from a2a.types import Message, Part, TaskState
from a2a.types import Role as A2ARole

from tests.e2e.demo import REPO, SECRET_VARIABLES, Demo, Driver, Event
from tiny_harness.harness.media import PCM_MEDIA_TYPE
from tiny_harness.jsontypes import JsonObject

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]

EXAMPLE = REPO / "examples" / "multimodal"
FIXTURES = EXAMPLE / "fixtures"
PNG = b"\x89PNG\r\n\x1a\n"
PCM_RATE = 24_000  # PCM_MEDIA_TYPE: 16-bit mono at 24 kHz
LATENCY_TARGET_SECONDS = 1.5  # NFR latency: reported, not a gate (it depends on OpenAI)

PHOTO_TEXT = "Here is a photo of my living room. Describe it in two sentences."
BACK_REFERENCE = "Now make the sofa in the first photo green, and show me."


class MultimodalDemo(Demo):
    """The demo's config for this run: the multimodal plugin, every media service on."""

    def config_text(self) -> str:
        base = f"http://127.0.0.1:{self.port}"
        state = self.root / "state"
        return "\n".join(
            [
                f'plugins = ["{EXAMPLE}"]',
                "[temporal]",
                'mode = "embedded"',
                f'task_queue = "{self.task_queue}"',
                "search_attributes = false",
                "[openai]",
                'model = "gpt-6.1-sol"',
                'timeout = "PT120S"',
                "max_output_tokens = 2000",
                "[media]",
                f'dir = "{state / "media"}"',
                "[speech_to_text]",
                'model = "gpt-4o-mini-transcribe"',
                "[text_to_speech]",
                'model = "gpt-4o-mini-tts"',
                'voice = "coral"',
                "[image_generation]",
                'model = "gpt-image-2"',
                "[server]",
                f'bind = "127.0.0.1:{self.port}"',
                f'base_url = "{base}"',
                "[store]",
                f'sqlite_path = "{state / "tiny-harness.sqlite3"}"',
                "[o11y]",
                'log_level = "INFO"',
                f'trace_file = "{self.trace_file}"',
                "",
            ]
        )


@dataclass
class Speech:
    """One spoken reply read through the media route as a surface reads it."""

    url: str
    started: float
    first_chunk_at: float | None = None
    pcm: bytearray = field(default_factory=bytearray)


@dataclass
class Turn:
    """What one message's stream showed."""

    events: list[Event] = field(default_factory=lambda: list[Event]())
    final_at: float | None = None
    state: int | None = None

    def artifacts(self, prefix: str) -> list[JsonObject]:
        found: list[JsonObject] = []
        for event in self.events:
            update = event.raw.get("artifactUpdate")
            if not isinstance(update, dict):
                continue
            artifact = cast(JsonObject, cast(JsonObject, update).get("artifact", {}))
            if str(artifact.get("artifactId", "")).startswith(prefix):
                found.append(artifact)
        return found


def parts_of(artifact: JsonObject) -> list[JsonObject]:
    return cast(list[JsonObject], artifact.get("parts", []))


def file_urls(artifact: JsonObject, media_prefix: str) -> list[str]:
    return [
        str(p["url"])
        for p in parts_of(artifact)
        if "url" in p and str(p.get("mediaType", "")).startswith(media_prefix)
    ]


def message(
    text: str,
    files: list[tuple[Path, str]],
    *,
    context_id: str,
    task_id: str | None,
    voice: bool = False,
    speak: bool = False,
) -> Message:
    """A user message with ``raw`` file parts, as a surface sends it."""
    parts = [Part(text=text)] if text else []
    for path, media_type in files:
        part = Part(raw=path.read_bytes(), media_type=media_type, filename=path.name)
        if voice:
            with wave.open(str(path)) as w:
                duration_ms = round(w.getnframes() * 1000 / w.getframerate())
            part.metadata.update({"voice": True, "durationMs": duration_ms})
        parts.append(part)
    msg = Message(
        message_id=uuid.uuid4().hex, context_id=context_id, role=A2ARole.ROLE_USER, parts=parts
    )
    if task_id is not None:
        msg.task_id = task_id
    msg.metadata.update({"participant_id": "alice"})
    if speak:
        msg.metadata.update({"speak": True})
    return msg


async def read_speech(http: httpx.AsyncClient, speech: Speech) -> None:
    async with http.stream("GET", speech.url) as response:
        response.raise_for_status()
        assert response.headers["content-type"].startswith("audio/L16")
        async for chunk in response.aiter_bytes():
            if chunk and speech.first_chunk_at is None:
                speech.first_chunk_at = time.monotonic()
            speech.pcm.extend(chunk)


async def turn(
    driver: Driver, msg: Message, http: httpx.AsyncClient, speeches: list[Speech]
) -> Turn:
    """Send ``msg``; start reading each speech artifact the moment it arrives."""
    out = Turn()
    readers: list[asyncio.Task[None]] = []

    def on_event(event: Event) -> None:
        print(event.line())
        out.events.append(event)
        if event.state in (TaskState.TASK_STATE_INPUT_REQUIRED, TaskState.TASK_STATE_COMPLETED):
            out.final_at = time.monotonic()
        for artifact in out.artifacts("speech:")[len(readers) :]:
            [url] = file_urls(artifact, "audio/L16")
            speech = Speech(url=url, started=time.monotonic())
            speeches.append(speech)
            readers.append(asyncio.create_task(read_speech(http, speech)))

    out.state = await driver.send(msg, on_event=on_event)
    if readers:
        async with asyncio.timeout(180):
            await asyncio.gather(*readers)
    return out


async def fetch(http: httpx.AsyncClient, url: str) -> bytes:
    response = await http.get(url)
    response.raise_for_status()
    return response.content


def tool_calls(demo: Demo, name: str) -> int:
    return sum(
        1
        for s in demo.spans()
        if cast(JsonObject, s.get("attributes", {})).get("gen_ai.tool.name") == name
    )


def pcm_wav(pcm: bytes) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(PCM_RATE)
        w.writeframes(pcm)
    return out.getvalue()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def demo() -> AsyncIterator[Demo]:
    instance = MultimodalDemo.create("multimodal", embedded=True)
    try:
        await instance.start_server()  # embedded mode runs the worker in-process
        yield instance
    finally:
        instance.stop()


async def test_the_multimodal_demo_scenario_runs_end_to_end(demo: Demo) -> None:
    """
    Feature: The multi-modal demo
    Requirement: docs/specs/issue-38/requirements.md#R7.2
    Requirement: docs/specs/issue-38/requirements.md#R7.3

    Scenario: photo, audio file, voice turn, spoken reply, generated image, back-reference
        Given examples/multimodal on an embedded Temporal with OpenAI for every media service
        And the agent card lists image and audio input and image and PCM output
        When alice sends the room photo with a question
        Then the photo is stored and echoed as a media URL and the agent describes the room
        When alice attaches question.wav
        Then the audio file is transcribed and the agent answers
        When alice sends followup.wav as a voice recording with speak=true
        Then its transcript is shown, the agent calls generate_image and the image is a PNG
        And the reply is spoken as a PCM stream that starts after the reply's final status
        When alice asks to make the sofa in the first photo green
        Then the agent generates another image
        And no secret, media byte or base64 of media reached the trace or the log
    """
    room = FIXTURES / "room.jpg"
    question = FIXTURES / "question.wav"
    followup = FIXTURES / "followup.wav"
    driver = Driver(demo)
    speeches: list[Speech] = []
    headers = {"X-Participant-Id": "alice"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(120, read=180), headers=headers) as http:
        card = (await http.get(f"{demo.base_url}/.well-known/agent-card.json")).json()
        try:
            ctx = driver.context_id
            photo = await turn(
                driver,
                message(PHOTO_TEXT, [(room, "image/jpeg")], context_id=ctx, task_id=None),
                http,
                speeches,
            )
            assert driver.task_id is not None
            tid = driver.task_id
            audio = await turn(
                driver,
                message("", [(question, "audio/wav")], context_id=ctx, task_id=tid),
                http,
                speeches,
            )
            images_before = tool_calls(demo, "generate_image")
            voice = await turn(
                driver,
                message(
                    "",
                    [(followup, "audio/wav")],
                    context_id=ctx,
                    task_id=tid,
                    voice=True,
                    speak=True,
                ),
                http,
                speeches,
            )
            images_after_voice = tool_calls(demo, "generate_image")
            back = await turn(
                driver, message(BACK_REFERENCE, [], context_id=ctx, task_id=tid), http, speeches
            )
            images_after_back = tool_calls(demo, "generate_image")
            generated = [
                await fetch(http, url)
                for t in (voice, back)
                for a in t.artifacts("image:")
                for url in file_urls(a, "image/")
            ]
            echoed_photo = [
                await fetch(http, url)
                for a in photo.artifacts("message:")
                for url in file_urls(a, "image/jpeg")
            ]
            final = await driver.complete()
        finally:
            await driver.close()

    # --- evidence --------------------------------------------------------------------------
    speech = speeches[0] if speeches else None
    latency = (
        speech.first_chunk_at - voice.final_at
        if speech is not None and speech.first_chunk_at is not None and voice.final_at is not None
        else None
    )
    summary = {
        "latency_first_chunk_after_final_status_s": latency,
        "latency_target_s": LATENCY_TARGET_SECONDS,
        "speech_bytes": len(speech.pcm) if speech else 0,
        "speech_seconds": len(speech.pcm) / (2 * PCM_RATE) if speech else 0,
        "generated_images": len(generated),
        "generate_image_calls": images_after_back,
        "states": [
            TaskState.Name(s) if s is not None else None
            for s in (photo.state, audio.state, voice.state, back.state)
        ],
    }
    print(json.dumps(summary, indent=2))
    demo.write_evidence("multimodal-transcript.txt", driver.transcript())
    demo.write_evidence("multimodal-summary.json", json.dumps(summary, indent=2))
    target = demo.evidence_dir()
    if target is not None:
        target.mkdir(parents=True, exist_ok=True)
        if generated:
            (target / "generated.png").write_bytes(generated[0])
        if speech is not None:
            (target / "reply-excerpt.wav").write_bytes(
                pcm_wav(bytes(speech.pcm[: 5 * 2 * PCM_RATE]))
            )

    # --- the card --------------------------------------------------------------------------
    assert "image/jpeg" in card["defaultInputModes"] and "audio/wav" in card["defaultInputModes"]
    assert "image/png" in card["defaultOutputModes"]
    assert PCM_MEDIA_TYPE in card["defaultOutputModes"]

    # --- each turn parks the task awaiting the next message --------------------------------
    for t in (photo, audio, voice, back):
        assert t.state == TaskState.TASK_STATE_INPUT_REQUIRED, driver.transcript()
    assert final == TaskState.TASK_STATE_COMPLETED, driver.transcript()

    # --- the photo is stored and echoed by reference ---------------------------------------
    assert echoed_photo == [room.read_bytes()]

    # --- the audio file and the voice turn are transcribed ---------------------------------
    for t in (audio, voice):
        [transcript] = t.artifacts("transcript:")
        text = " ".join(str(p.get("text", "")) for p in parts_of(transcript)).lower()
        assert text.strip(), "an empty transcript"
    voice_text = " ".join(
        str(p.get("text", "")) for a in voice.artifacts("transcript:") for p in parts_of(a)
    ).lower()
    assert "mock" in voice_text or "image" in voice_text, voice_text

    # --- the voice turn: a generated image and a spoken reply ------------------------------
    assert images_after_voice > images_before, "the voice turn generated no image"
    assert voice.artifacts("image:"), "no image artifact in the voice turn"
    assert generated and all(image.startswith(PNG) for image in generated)
    assert speech is not None, "the voice turn was not spoken"
    assert len(speeches) == 1, "only the voice turn asked for speech"
    assert speech.pcm and len(speech.pcm) % 2 == 0, len(speech.pcm)
    assert latency is not None and latency >= 0, latency

    # --- the back-reference: the agent works on the first photo again ----------------------
    assert images_after_back > images_after_voice, "the back-reference generated no image"
    assert back.artifacts("image:")

    # --- nothing secret or binary in the trace or the log ----------------------------------
    text = demo.trace_file.read_text() + demo.read_log("server.log")
    for name in SECRET_VARIABLES:
        value = os.environ.get(name)
        assert not value or value not in text, f"{name} leaked into the trace or log"
    blobs = [room.read_bytes(), question.read_bytes(), followup.read_bytes(), *generated]
    blobs.append(bytes(speech.pcm[: 3 * 1024]))
    for blob in blobs:
        assert base64.b64encode(blob).decode()[:32] not in text
        assert repr(blob)[2:40] not in text
