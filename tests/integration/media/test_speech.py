"""Feature: Spoken replies, streamed
Requirement: docs/specs/issue-38/requirements.md#R4

WHEN the message a reply answers asked for speech and text-to-speech is configured, the
workflow opens a growing speech object, shows it as the ``speech:<mediaId>`` artifact
before the reply's final status, and speaks the reply into it as a tracked speech job
while the mailbox keeps draining. Each attempt writes its own generation; a failure
closes it failed and tells the user speech is unavailable; rollover and completion wait
for the speech, and a cancel stops it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path

import pytest
from a2a.types import TaskState
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from tests.fixtures import media as fx
from tests.integration.durable.conftest import (
    awaiting_next_message,
    close,
    env,
    send,
    start,
    until,
)
from tests.integration.media.flows import (
    BASE_URL,
    artifacts,
    ids,
    media_harness,
    media_task,
    parts_of,
    replied,
    status_texts,
    with_files,
)
from tiny_harness.errors import ProviderError, RetryableProviderError
from tiny_harness.harness.media import (
    PCM_MEDIA_TYPE,
    FileMediaStore,
    MediaFailed,
    MediaInterrupted,
    MediaRef,
)
from tiny_harness.harness.models import FakeSpeechToText, FakeTextToSpeech, scripted
from tiny_harness.harness.models.speech import SpeakCall
from tiny_harness.service.durable.models import EventEntry
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

ONE = b"\x01\x00" * 240
TWO = b"\x02\x00" * 240
SPEECH_UNAVAILABLE = "speech unavailable"


class GatedTTS(FakeTextToSpeech):
    """Yields the first chunk, then waits for this call's gate before the rest."""

    def __init__(self) -> None:
        super().__init__([ONE, TWO])
        self.gates: list[asyncio.Event] = []

    async def stream(
        self, text: str, *, voice: str | None = None, instructions: str | None = None
    ) -> AsyncIterator[bytes]:
        self.calls.append(SpeakCall(text, voice, instructions))
        gate = asyncio.Event()
        self.gates.append(gate)
        yield ONE
        await gate.wait()
        yield TWO


class FlakyTTS(FakeTextToSpeech):
    """The first call yields one chunk, waits for the gate, then fails as retryable; every
    later call speaks ``TWO`` twice."""

    def __init__(self) -> None:
        super().__init__([TWO, TWO])
        self.gate = asyncio.Event()

    async def stream(
        self, text: str, *, voice: str | None = None, instructions: str | None = None
    ) -> AsyncIterator[bytes]:
        self.calls.append(SpeakCall(text, voice, instructions))
        if len(self.calls) == 1:
            yield ONE
            await self.gate.wait()
            raise RetryableProviderError("busy", provider="fake", status=503)
        for chunk in self.chunks:
            yield chunk


def speech_of(events: tuple[EventEntry, ...]) -> list[str]:
    """The media id of every speech artifact, in order."""
    return [str(a["artifactId"]).removeprefix("speech:") for a in artifacts(events, "speech:")]


async def wait_for(predicate: Callable[[], bool], timeout: float = 10.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the condition never held")


async def spoken(store: FileMediaStore, task_id: str, media_id: str) -> MediaRef:
    """The speech object once it is done (its ref then has its size)."""
    for _ in range(500):
        ref = await store.lookup(task_id, media_id)
        if ref is not None and ref.size > 0:
            return ref
        await asyncio.sleep(0.02)
    raise AssertionError("the speech never finished")


async def read_all(store: FileMediaStore, ref: MediaRef) -> bytes:
    return b"".join([c async for c in store.read_stream(ref, poll=0.01, idle_timeout=5)])


async def assert_failed(store: FileMediaStore, task_id: str, media_id: str) -> None:
    ref = await store.lookup(task_id, media_id)
    assert ref is not None
    with pytest.raises(MediaFailed):
        await read_all(store, ref)


async def test_a_voice_turn_is_transcribed_answered_and_spoken(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Spoken replies, streamed
    Requirement: docs/specs/issue-38/requirements.md#R4.1

    Scenario: a voice turn is transcribed, answered and spoken
        Given an agent with speech-to-text and text-to-speech
        When alice sends a voice recording with speak=true
        Then the recording is transcribed and the model answers "**A** cat, grey."
        And the event log shows the speech:<mediaId> artifact, a url file part of the PCM type
        And text-to-speech speaks "A cat, grey." without the markdown
        And the speech object holds every chunk once it is done
    """
    stt = FakeSpeechToText(["what is in the photo I sent?"])
    tts = FakeTextToSpeech([ONE, TWO])
    h, store = await media_harness(tmp_path, [scripted("**A** cat, grey.")], stt=stt, tts=tts)
    tq, tid = ids()
    msg = await with_files(
        store,
        tid,
        "",
        [(fx.wav(0.5), "audio/wav", "question.wav")],
        message_id="m1",
        voice=True,
        speak=True,
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        await awaiting_next_message(handle)
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert len(artifacts(page.events, "transcript:")) == 1
        [speech] = artifacts(page.events, "speech:")
        media_id = str(speech["artifactId"]).removeprefix("speech:")
        [part] = parts_of(speech)
        assert part["mediaType"] == PCM_MEDIA_TYPE
        assert part["url"] == f"{BASE_URL}/media/{tid}/{media_id}"
        assert speech["metadata"] == {"mediaId": media_id}
        ref = await spoken(store, tid, media_id)
        assert await read_all(store, ref) == ONE + TWO
        assert [c.text for c in tts.calls] == ["A cat, grey."]
        await close(handle)


async def test_the_speech_artifact_arrives_before_the_final_status(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Spoken replies, streamed
    Requirement: docs/specs/issue-38/requirements.md#R4.2

    Scenario: the speech artifact arrives before the final status
        Given an agent with text-to-speech
        When alice sends a message with speak=true, then one with speak=false
        Then the speech artifact is logged before the first reply's INPUT_REQUIRED status
        And the second reply is not spoken
    """
    tts = FakeTextToSpeech([ONE])
    h, store = await media_harness(tmp_path, [scripted("Hello."), scripted("Quiet.")], tts=tts)
    tq, tid = ids()
    first = await with_files(store, tid, "hi", [], message_id="m1", speak=True)
    second = await with_files(store, tid, "shh", [], message_id="m2")
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), first)
        await awaiting_next_message(handle)
        await handle.execute_update(TaskWorkflow.inbox, second)  # pyright: ignore[reportUnknownMemberType]
        await until(handle, replied("Quiet."))
        page = await handle.query(TaskWorkflow.events_since, 0)
        kinds = [
            "speech"
            if e.kind == "artifact_update" and speech_of((e,))
            else ("reply" if e.kind == "status_update" and "Hello." in status_texts((e,)) else "")
            for e in page.events
        ]
        assert kinds.index("speech") < kinds.index("reply")
        assert len(speech_of(page.events)) == 1
        assert len(tts.calls) == 1
        await close(handle)


async def test_a_retry_during_speech_starts_a_new_generation_and_the_reader_is_told(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Spoken replies, streamed
    Requirement: docs/specs/issue-38/requirements.md#R4.2

    Scenario: a retry during speech starts a new generation and the reader is told
        Given a reader following a spoken reply's first chunk
        When text-to-speech fails with a retryable error and the workflow retries
        Then the retry writes a new generation from the start, fencing the first
        And the reader's stream is interrupted
        And a replay reads the retry's speech in full
    """
    tts = FlakyTTS()
    h, store = await media_harness(tmp_path, [scripted("Hello.")], tts=tts)
    tq, tid = ids()
    msg = await with_files(store, tid, "hi", [], message_id="m1", speak=True)
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        await awaiting_next_message(handle)
        page = await handle.query(TaskWorkflow.events_since, 0)
        [media_id] = speech_of(page.events)
        await wait_for(lambda: len(tts.calls) == 1)
        ref = await store.lookup(tid, media_id)
        assert ref is not None
        chunks = store.read_stream(ref, poll=0.01, idle_timeout=5)
        assert await asyncio.wait_for(anext(chunks), timeout=5) == ONE
        tts.gate.set()
        with pytest.raises(MediaInterrupted):
            async for _ in chunks:
                pass
        done = await spoken(store, tid, media_id)
        assert await read_all(store, done) == TWO + TWO
        assert len(tts.calls) == 2
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert SPEECH_UNAVAILABLE not in status_texts(page.events)
        await close(handle)


async def test_speech_that_fails_leaves_the_text_and_a_note(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Spoken replies, streamed
    Requirement: docs/specs/issue-38/requirements.md#R4.5

    Scenario: speech that fails leaves the text and a note
        Given an agent whose text-to-speech refuses the reply (a provider error)
        When alice sends a message with speak=true
        Then the reply's text is delivered and the task waits for the next message
        And the speech object is closed failed, so a reader's stream aborts
        And the task's status says "speech unavailable"
    """
    tts = FakeTextToSpeech([ONE], error=ProviderError("refused", provider="fake", status=400))
    h, store = await media_harness(tmp_path, [scripted("Hello.")], tts=tts)
    tq, tid = ids()
    msg = await with_files(store, tid, "hi", [], message_id="m1", speak=True)
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        await until(handle, replied("Hello."))
        page = await handle.query(TaskWorkflow.events_since, 0)
        [media_id] = speech_of(page.events)
        await assert_failed(store, tid, media_id)
        for _ in range(250):
            page = await handle.query(TaskWorkflow.events_since, 0)
            if SPEECH_UNAVAILABLE in status_texts(page.events):
                break
            await asyncio.sleep(0.02)
        assert status_texts(page.events).count(SPEECH_UNAVAILABLE) == 1
        assert len(tts.calls) == 1  # a provider's refusal is not retried
        await until(handle, replied("Hello."))
        await close(handle)


async def test_rollover_and_completion_wait_for_speech_cancel_stops_it(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Spoken replies, streamed
    Requirement: docs/specs/issue-38/requirements.md#R4

    Scenario: rollover and completion wait for speech; cancel stops it
        Given a conversation whose history is due to roll over, with a reply being spoken
        When alice sends the next message
        Then the workflow waits for the speech to finish before it continues as new
        And the new run answers the message and speaks the reply
        When the task is cancelled while that reply is being spoken
        Then the speech job is cancelled at once and its object is closed failed
    """
    tts = GatedTTS()
    h, store = await media_harness(tmp_path, [scripted("One."), scripted("Two.")], tts=tts)
    h.heartbeat_every = 0.2
    tq, tid = ids()
    first = await with_files(store, tid, "one", [], message_id="m1", speak=True)
    second = await with_files(store, tid, "two", [], message_id="m2", speak=True)
    begin = start(media_task(tid), history_event_bound=30, heartbeat_timeout=timedelta(seconds=2))
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, begin, first)
        await until(handle, replied("One."))
        await wait_for(lambda: len(tts.gates) == 1)
        await handle.execute_update(TaskWorkflow.inbox, second)  # pyright: ignore[reportUnknownMemberType]
        await asyncio.sleep(0.5)
        assert len(h.llm.requests) == 1  # the rollover waits for the speech
        tts.gates[0].set()
        await until(handle, replied("Two."))
        page = await handle.query(TaskWorkflow.events_since, 0)
        first_id, second_id = speech_of(page.events)
        assert await read_all(store, await spoken(store, tid, first_id)) == ONE + TWO
        first_run = env.client.get_workflow_handle(tid, run_id=handle.first_execution_run_id)
        assert (await first_run.describe()).status is WorkflowExecutionStatus.CONTINUED_AS_NEW
        await wait_for(lambda: len(tts.gates) == 2)
        result = await asyncio.wait_for(close(handle), timeout=15)
        assert result.status.state == TaskState.TASK_STATE_CANCELED
        await assert_failed(store, tid, second_id)


async def test_completion_waits_for_the_last_spoken_reply(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Spoken replies, streamed
    Requirement: docs/specs/issue-38/requirements.md#R4

    Scenario: completion waits for the last spoken reply
        Given a delegated task whose message asked for speech
        When the task completes with its reply
        Then the COMPLETED status follows the speech artifact
        And the workflow stays open until the reply has been spoken in full
    """
    tts = GatedTTS()
    h, store = await media_harness(tmp_path, [scripted("Done.")], tts=tts)
    tq, tid = ids()
    msg = await with_files(store, tid, "finish", [], message_id="m1", speak=True)
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid, lifecycle="delegated")), msg)
        await until(handle, lambda t: t.state_name == "COMPLETED")
        await wait_for(lambda: len(tts.gates) == 1)
        await asyncio.sleep(0.3)
        assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING
        tts.gates[0].set()
        result = await asyncio.wait_for(handle.result(), timeout=15)
        assert result.status.message.parts[0].text == "Done."
        page = await handle.query(TaskWorkflow.events_since, 0)
        [media_id] = speech_of(page.events)
        ref = await store.lookup(tid, media_id)
        assert ref is not None and ref.size == len(ONE + TWO)


async def test_speech_still_running_when_the_drain_ends_is_stopped_with_a_note(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Spoken replies, streamed
    Requirement: docs/specs/issue-38/requirements.md#R4.5

    Scenario: speech still running when the drain ends is stopped with a note
        Given a delegated task with [media] speech_drain of half a second
        When the task completes while its reply's speech never finishes
        Then the workflow stops the speech job after the drain and closes
        And the speech object is closed failed and the status says "speech unavailable"
    """
    tts = GatedTTS()
    h, store = await media_harness(tmp_path, [scripted("Done.")], tts=tts)
    h.heartbeat_every = 0.2
    tq, tid = ids()
    msg = await with_files(store, tid, "finish", [], message_id="m1", speak=True)
    begin = start(
        media_task(tid, lifecycle="delegated"),
        heartbeat_timeout=timedelta(seconds=2),
        speech_drain=timedelta(milliseconds=500),
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, begin, msg)
        await asyncio.wait_for(handle.result(), timeout=20)
        page = await handle.query(TaskWorkflow.events_since, 0)
        [media_id] = speech_of(page.events)
        await assert_failed(store, tid, media_id)
        assert SPEECH_UNAVAILABLE in status_texts(page.events)
