"""Feature: Audio reaches the model
Requirement: docs/specs/issue-38/requirements.md#R3.4

An audio attachment reaches the model natively WHERE the model takes that audio type, and
otherwise as the transcript from speech-to-text, which is kept on the attachment in the
history and shown to the surfaces as a ``transcript:<mediaId>`` artifact. With no
speech-to-text, or when it fails, the user is told and the turn goes on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.fixtures import media as fx
from tests.integration.durable.conftest import awaiting_next_message, close, env, send, start
from tests.integration.media.flows import (
    artifacts,
    ids,
    media_harness,
    media_task,
    parts_of,
    status_texts,
    with_files,
)
from tiny_harness.errors import ProviderError
from tiny_harness.harness.models import FakeSpeechToText, MessageItem, scripted
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]


async def test_a_recording_is_transcribed_and_the_transcript_is_shown(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Audio reaches the model
    Requirement: docs/specs/issue-38/requirements.md#R3.4

    Scenario: a recording is transcribed and the transcript is shown
        Given an agent with speech-to-text whose model takes no audio
        When alice sends a voice recording question.wav
        Then speech-to-text gets the recording once
        And the model gets the transcript, labelled with the file's name
        And the event log shows the transcript as the artifact transcript:<mediaId>
    """
    raw = fx.wav(0.5)
    stt = FakeSpeechToText(["what is in the photo I sent?"])
    h, store = await media_harness(tmp_path, [scripted("A cat.")], stt=stt)
    tq, tid = ids()
    msg = await with_files(
        store, tid, "", [(raw, "audio/wav", "question.wav")], message_id="m1", voice=True
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        await awaiting_next_message(handle)
        [call] = stt.calls
        assert (call.audio, call.media_type, call.name) == (raw, "audio/wav", "question.wav")
        [request] = h.llm.requests
        [item] = [i for i in request.input if isinstance(i, MessageItem) and i.media]
        [attachment] = item.media
        assert attachment.transcript == "what is in the photo I sent?"
        assert attachment.data is None
        assert attachment.ref.voice
        page = await handle.query(TaskWorkflow.events_since, 0)
        [shown] = artifacts(page.events, "transcript:")
        assert shown["artifactId"] == f"transcript:{attachment.ref.id}"
        assert [p.get("text") for p in parts_of(shown)] == ["what is in the photo I sent?"]
        assert shown["metadata"] == {"mediaId": attachment.ref.id}
        await close(handle)


async def test_native_audio_skips_speech_to_text(env: WorkflowEnvironment, tmp_path: Path) -> None:
    """
    Feature: Audio reaches the model
    Requirement: docs/specs/issue-38/requirements.md#R3.4

    Scenario: native audio skips speech-to-text
        Given an agent with speech-to-text whose model takes audio/wav input
        When alice sends question.wav
        Then speech-to-text is not called
        And the model gets the recording's bytes as audio input
        And no transcript artifact is shown
    """
    raw = fx.wav(0.5)
    stt = FakeSpeechToText([])
    h, store = await media_harness(
        tmp_path,
        [scripted("I heard you.")],
        modalities=frozenset({"text", "audio"}),
        audio_formats=frozenset({"audio/wav", "audio/mpeg"}),
        stt=stt,
    )
    tq, tid = ids()
    msg = await with_files(
        store, tid, "listen", [(raw, "audio/wav", "question.wav")], message_id="m1"
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        await awaiting_next_message(handle)
        assert stt.calls == []
        [request] = h.llm.requests
        [item] = [i for i in request.input if isinstance(i, MessageItem) and i.media]
        [attachment] = item.media
        assert (attachment.data, attachment.transcript) == (raw, None)
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert artifacts(page.events, "transcript:") == []
        await close(handle)


async def test_audio_with_no_speech_to_text_configured_gets_a_note(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Audio reaches the model
    Requirement: docs/specs/issue-38/requirements.md#R1.6

    Scenario: audio with no speech-to-text configured gets a note
        Given an agent with no speech-to-text whose model takes no audio
        When alice sends "listen" with question.wav
        Then the model gets the text and a line saying the audio was not given to it
        And the task's status tells the user no speech-to-text is configured
        And the task answers and waits for the next message
    """
    h, store = await media_harness(tmp_path, [scripted("I cannot hear it.")])
    tq, tid = ids()
    msg = await with_files(
        store, tid, "listen", [(fx.wav(0.5), "audio/wav", "question.wav")], message_id="m1"
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        await awaiting_next_message(handle)
        [request] = h.llm.requests
        [item] = [i for i in request.input if isinstance(i, MessageItem) and "listen" in i.text]
        assert item.media == ()
        assert item.text == (
            "[alice] listen\n[audio question.wav not given to the model: no transcript]"
        )
        page = await handle.query(TaskWorkflow.events_since, 0)
        notes = [t for t in status_texts(page.events) if "speech-to-text" in t]
        assert notes == [
            "audio question.wav was not given to the model: no speech-to-text is configured"
        ]
        await close(handle)


async def test_a_failed_transcription_leaves_a_note_and_the_turn_continues(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Audio reaches the model
    Requirement: docs/specs/issue-38/requirements.md#R3.4

    Scenario: a failed transcription leaves a note and the turn continues
        Given an agent whose speech-to-text refuses the recording (a provider error)
        When alice sends question.wav
        Then the attachment's transcript is "(transcription failed)"
        And the task's status says the transcription failed
        And the model still answers and the task waits for the next message
    """
    stt = FakeSpeechToText([ProviderError("bad audio", provider="fake", status=400)])
    h, store = await media_harness(tmp_path, [scripted("Sorry?")], stt=stt)
    tq, tid = ids()
    msg = await with_files(
        store, tid, "", [(fx.wav(0.5), "audio/wav", "question.wav")], message_id="m1", voice=True
    )
    async with h.worker(env.client, tq):
        handle = await send(env.client, tq, start(media_task(tid)), msg)
        await awaiting_next_message(handle)
        [request] = h.llm.requests
        [item] = [i for i in request.input if isinstance(i, MessageItem) and i.media]
        assert item.media[0].transcript == "(transcription failed)"
        page = await handle.query(TaskWorkflow.events_since, 0)
        assert "transcription of question.wav failed" in status_texts(page.events)
        assert artifacts(page.events, "transcript:") == []
        await close(handle)
