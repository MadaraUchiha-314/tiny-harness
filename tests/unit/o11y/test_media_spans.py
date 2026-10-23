"""Media spans (issue-38 NFR observability): ``media.intake`` on the executor, and
``transcribe {model}``, ``speech {model}`` and ``image {model}`` like ``chat`` — model,
endpoint, sizes, duration and the media id; never bytes, base64 or a transcript."""

from __future__ import annotations

import base64
import json
from collections.abc import Generator
from pathlib import Path
from typing import cast

import pytest
from a2a.server.context import ServerCallContext
from a2a.types import Message, Part, Role
from a2a.utils.errors import InvalidParamsError
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from temporalio.client import Client
from temporalio.testing import ActivityEnvironment

from tests.fixtures import media as fx
from tests.integration.durable.conftest import Harness
from tiny_harness.config import MediaConfig, O11yConfig
from tiny_harness.errors import ProviderError
from tiny_harness.harness.core import HarnessTask, Participant, TaskExtensionData
from tiny_harness.harness.core import Role as TaskRole
from tiny_harness.harness.core.intrinsics import GenerateImageTool, TaskContext
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore, MediaIntake, spans
from tiny_harness.harness.models import (
    FakeImageGenerator,
    FakeSpeechToText,
    FakeTextToSpeech,
    Transcript,
)
from tiny_harness.harness.models.speech import SpeechModelInfo
from tiny_harness.harness.tools import ToolCall, ToolResult
from tiny_harness.service.a2a import HarnessExecutor, PollingEventBridge
from tiny_harness.service.a2a.task_store import PARTICIPANT_STATE_KEY
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.models import (
    OpenSpeechIn,
    SpeakIn,
    TranscribeIn,
    WorkflowConfig,
)
from tiny_harness.service.o11y import configure_tracing

TRANSCRIPT = "the secret recipe is cardamom"


@pytest.fixture
def exporter() -> Generator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = configure_tracing(O11yConfig(), exporter=exporter, set_global=False)
    with spans.tracing(provider):
        yield exporter


@pytest.fixture
def store(tmp_path: Path) -> FileMediaStore:
    return FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), tmp_path)


def task() -> HarnessTask:
    ext = TaskExtensionData(
        name="n",
        goal="g",
        participants=(Participant(id="alice", kind="human", role=TaskRole.REPORTER),),
    )
    return HarnessTask.new("t-1", "ctx-1", ext)


def only(exporter: InMemorySpanExporter, name: str) -> ReadableSpan:
    [span] = [s for s in exporter.get_finished_spans() if s.name == name]
    return span


def attributes(span: ReadableSpan) -> dict[str, object]:
    return dict(span.attributes or {})


def carries_no(span: ReadableSpan, *blobs: bytes, text: str = TRANSCRIPT) -> None:
    rendered = json.dumps(attributes(span), default=str)
    for blob in blobs:
        assert base64.b64encode(blob).decode()[:32] not in rendered
        assert repr(blob)[2:40] not in rendered
    assert text not in rendered


async def test_transcribe_span(exporter: InMemorySpanExporter, store: FileMediaStore) -> None:
    audio = fx.wav(1.5)
    ref = await store.put("t-1", audio, media_type="audio/wav", name="q.wav", duration_ms=1_500)
    stt = FakeSpeechToText([Transcript(text=TRANSCRIPT, duration_ms=1_500)])
    stt.info = SpeechModelInfo(
        provider="openai", model="mini-stt", endpoint="https://stt.example:8443"
    )
    h = Harness([], media_store=store, speech_to_text=stt)
    arg = TranscribeIn(task_id="t-1", correlation_id="c", task=task().proto, ref=ref)
    out = await ActivityEnvironment().run(Activities(h.engine).transcribe, arg)
    assert out.text == TRANSCRIPT
    span = only(exporter, "transcribe mini-stt")
    assert (
        attributes(span).items()
        >= {
            "gen_ai.operation.name": "transcription",
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": "mini-stt",
            "server.address": "stt.example",
            "server.port": 8443,
            "tiny_harness.task_id": "t-1",
            "tiny_harness.media.id": ref.id,
            "tiny_harness.media.input_bytes": len(audio),
            "tiny_harness.media.duration_ms": 1_500,
            "tiny_harness.media.output_chars": len(TRANSCRIPT),
        }.items()
    )
    carries_no(span, audio)


async def test_a_failed_transcription_span_is_an_error(
    exporter: InMemorySpanExporter, store: FileMediaStore
) -> None:
    ref = await store.put("t-1", fx.wav(0.5), media_type="audio/wav", name="q.wav")
    stt = FakeSpeechToText([ProviderError("refused", provider="fake", status=400)])
    h = Harness([], media_store=store, speech_to_text=stt)
    arg = TranscribeIn(task_id="t-1", correlation_id="c", task=task().proto, ref=ref)
    out = await ActivityEnvironment().run(Activities(h.engine).transcribe, arg)
    assert out.mode == "failed"
    span = only(exporter, "transcribe fake-stt")
    assert span.status.status_code is StatusCode.ERROR
    assert attributes(span)["error.type"] == "ProviderError"


async def test_speech_span(exporter: InMemorySpanExporter, store: FileMediaStore) -> None:
    chunk = bytes(range(256)) * 4
    tts = FakeTextToSpeech([chunk, chunk])
    h = Harness([], media_store=store, text_to_speech=tts)
    activities = Activities(h.engine)
    env = ActivityEnvironment()
    await env.run(
        activities.open_speech, OpenSpeechIn(task_id="t-1", correlation_id="c", media_id="s1")
    )
    text = "**Hello** there."
    await env.run(
        activities.speak,
        SpeakIn(task_id="t-1", correlation_id="c", media_id="s1", text=text, max_attempts=3),
    )
    span = only(exporter, "speech fake-tts")
    assert (
        attributes(span).items()
        >= {
            "gen_ai.operation.name": "speech",
            "gen_ai.request.model": "fake-tts",
            "tiny_harness.media.id": "s1",
            "tiny_harness.media.input_chars": len("Hello there."),
            "tiny_harness.media.output_bytes": 2 * len(chunk),
            "tiny_harness.media.duration_ms": round(2 * len(chunk) / 2 / 24_000 * 1000),
            "tiny_harness.media.generation": 1,
        }.items()
    )
    carries_no(span, chunk, text="Hello there.")


async def test_image_span(exporter: InMemorySpanExporter, store: FileMediaStore) -> None:
    images = FakeImageGenerator()
    tool = GenerateImageTool(TaskContext(task()), images, store)
    prompt = "a green sofa in a bright room"
    result = await tool.invoke(
        ToolCall(call_id="c1", name="generate_image", arguments={"prompt": prompt, "alt": "Sofa"})
    )
    assert isinstance(result, ToolResult)
    ref = result.content[1].media
    assert ref is not None
    span = only(exporter, "image fake-image")
    assert (
        attributes(span).items()
        >= {
            "gen_ai.operation.name": "image_generation",
            "gen_ai.request.model": "fake-image",
            "tiny_harness.task_id": "t-1",
            "tiny_harness.media.id": ref.id,
            "tiny_harness.media.input_chars": len(prompt),
            "tiny_harness.media.output_bytes": ref.size,
            "tiny_harness.media.width": 1024,
            "tiny_harness.media.height": 1024,
        }.items()
    )
    carries_no(span, await store.get(ref), text=prompt)


class NoClient:
    def __getattr__(self, name: str) -> object:
        raise AssertionError("reached the workflow")


def executor(store: FileMediaStore) -> HarnessExecutor:
    client = cast(Client, NoClient())
    intake = MediaIntake(store, MediaConfig(max_file_bytes=4_096), base_url="http://h")
    return HarnessExecutor(
        client,
        task_queue="tq",
        bridge=PollingEventBridge(client),
        config=WorkflowConfig(search_attributes=False),
        media_intake=intake,
    )


async def execute(store: FileMediaStore, *parts: Part) -> None:
    from a2a.server.agent_execution import RequestContext
    from a2a.server.events import EventQueueLegacy
    from a2a.types import SendMessageRequest

    message = Message(message_id="m-1", role=Role.ROLE_USER, parts=list(parts))
    call = ServerCallContext()
    call.state[PARTICIPANT_STATE_KEY] = "alice"
    context = RequestContext(
        call,
        request=SendMessageRequest(message=message),
        task_id="t-1",
        context_id="ctx-1",
    )
    await executor(store).execute(context, EventQueueLegacy())


async def test_intake_span_counts_files_and_bytes(
    exporter: InMemorySpanExporter, store: FileMediaStore
) -> None:
    image = fx.png(4, 4)
    part = Part(raw=image, media_type="image/png", filename="photo.png")
    with pytest.raises(AssertionError, match="reached the workflow"):
        await execute(store, Part(text="look"), part)
    span = only(exporter, "media.intake")
    assert (
        attributes(span).items()
        >= {
            "tiny_harness.task_id": "t-1",
            "tiny_harness.media.count": 1,
            "tiny_harness.media.bytes": len(image),
        }.items()
    )
    assert "tiny_harness.media.rejection" not in attributes(span)
    carries_no(span, image)


async def test_intake_span_names_the_rejection(
    exporter: InMemorySpanExporter, store: FileMediaStore
) -> None:
    big = fx.png(4, 4, padding=8_192)
    with pytest.raises(InvalidParamsError):
        await execute(store, Part(raw=big, media_type="image/png", filename="big.png"))
    span = only(exporter, "media.intake")
    assert attributes(span)["tiny_harness.media.rejection"] == "too_large"
    assert span.status.status_code is StatusCode.ERROR


async def test_no_span_for_a_message_without_files(
    exporter: InMemorySpanExporter, store: FileMediaStore
) -> None:
    with pytest.raises(AssertionError, match="reached the workflow"):
        await execute(store, Part(text="hello"))
    assert [s.name for s in exporter.get_finished_spans()] == []
