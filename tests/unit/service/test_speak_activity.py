"""issue-38 self-review 1.6: the speak activity closes the provider's stream when it
stops early (a newer attempt fenced the object), not whenever it is collected."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO, cast

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from tests.integration.durable.conftest import Harness
from tiny_harness.errors import RetryableProviderError
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore, MediaRef, SpeechWriter
from tiny_harness.harness.models import FakeTextToSpeech
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.models import OpenSpeechIn, SpeakIn


class FencedMidway(FakeTextToSpeech):
    """After its first chunk is written, a newer attempt begins on the same object (so
    the next append is fenced); records whether its stream was closed early. It keeps
    every stream it made, so only an explicit close closes one."""

    def __init__(self, store: FileMediaStore) -> None:
        super().__init__([b"\x00\x00" * 100] * 3)
        self.store = store
        self.closed = 0
        self.streams: list[AsyncIterator[bytes]] = []

    def stream(
        self, text: str, *, voice: str | None = None, instructions: str | None = None
    ) -> AsyncIterator[bytes]:
        stream = self._stream()
        self.streams.append(stream)
        return stream

    async def _stream(self) -> AsyncIterator[bytes]:
        try:
            yield self.chunks[0]
            ref = await self.store.lookup("t-1", "s1")
            assert ref is not None
            await self.store.begin(ref)  # a newer attempt fences this one
            for chunk in self.chunks[1:]:
                yield chunk
        except GeneratorExit:
            self.closed += 1
            raise


async def test_a_fenced_speak_closes_the_speech_stream(tmp_path: Path) -> None:
    store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), tmp_path)
    tts = FencedMidway(store)
    activities = Activities(Harness([], media_store=store, text_to_speech=tts).engine)
    env = ActivityEnvironment()
    await env.run(
        activities.open_speech, OpenSpeechIn(task_id="t-1", correlation_id="c", media_id="s1")
    )
    arg = SpeakIn(task_id="t-1", correlation_id="c", media_id="s1", text="Hi.", max_attempts=3)
    with pytest.raises(ApplicationError) as caught:
        await env.run(activities.speak, arg)
    assert caught.value.type == "media.fenced"
    assert tts.closed == 1


class FailsAfterOneChunk(FakeTextToSpeech):
    """Yields one chunk, then a retryable provider failure."""

    def __init__(self) -> None:
        super().__init__([b"\x00\x00" * 100])

    def stream(
        self, text: str, *, voice: str | None = None, instructions: str | None = None
    ) -> AsyncIterator[bytes]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[bytes]:
        yield self.chunks[0]
        raise RetryableProviderError("busy", provider="fake", status=503)


async def test_a_retryable_failure_closes_the_writers_file_and_leaves_the_object_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """issue-38 self-review 2.9: an attempt that fails and will be retried releases its
    generation file at once, and does not mark the object failed (the retry writes it)."""
    store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), tmp_path)
    writers: list[SpeechWriter] = []
    begin = store.begin

    async def recording_begin(ref: MediaRef) -> SpeechWriter:
        writer = await begin(ref)
        writers.append(writer)
        return writer

    monkeypatch.setattr(store, "begin", recording_begin)
    activities = Activities(
        Harness([], media_store=store, text_to_speech=FailsAfterOneChunk()).engine
    )
    env = ActivityEnvironment()
    await env.run(
        activities.open_speech, OpenSpeechIn(task_id="t-1", correlation_id="c", media_id="s1")
    )
    arg = SpeakIn(task_id="t-1", correlation_id="c", media_id="s1", text="Hi.", max_attempts=3)
    with pytest.raises(ApplicationError) as caught:
        await env.run(activities.speak, arg)
    assert not caught.value.non_retryable
    [writer] = writers
    file = cast(BinaryIO, getattr(writer, "_file"))  # noqa: B009 - the writer's own file
    assert file.closed
    state = (tmp_path / "t-1" / "s1.state").read_text()
    assert not state.startswith(("failed", "done")), state
