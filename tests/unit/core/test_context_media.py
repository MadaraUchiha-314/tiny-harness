"""Media in the context budget (issue-38 R6.1, design critic 7): an image, a transcribed
audio file and a native audio file each count toward the window's size, so the budget
check and compaction see them."""

from __future__ import annotations

import math

import pytest

from tiny_harness.harness.core import (
    AgentState,
    ContextWindowManager,
    HarnessTask,
    Participant,
    Role,
    TaskExtensionData,
)
from tiny_harness.harness.core.context import AUDIO_TOKENS_PER_SECOND, IMAGE_TOKEN_ESTIMATE
from tiny_harness.harness.media import MediaAttachment, MediaKind, MediaRef
from tiny_harness.harness.models import LLMModelInfo, MessageItem
from tiny_harness.harness.models import Role as MessageRole


def _task() -> HarnessTask:
    return HarnessTask.new(
        "t-1",
        "ctx",
        TaskExtensionData(
            name="n",
            goal="g",
            participants=(Participant(id="a", kind="human", role=Role.REPORTER),),
        ),
    )


def _image(size: int = 10) -> MediaAttachment:
    ref = MediaRef(
        id="m1",
        task_id="t-1",
        kind=MediaKind.IMAGE,
        media_type="image/png",
        size=size,
        name="a.png",
    )
    return MediaAttachment(ref=ref)


def _audio(*, transcript: str | None = None, duration_ms: int | None = 2_500) -> MediaAttachment:
    ref = MediaRef(
        id="m2",
        task_id="t-1",
        kind=MediaKind.AUDIO,
        media_type="audio/wav",
        size=10,
        name="q.wav",
        duration_ms=duration_ms,
    )
    return MediaAttachment(ref=ref, transcript=transcript)


def _chars(
    *media: MediaAttachment, manager: ContextWindowManager | None = None, text: str = "hi"
) -> int:
    state = AgentState(task_id="t-1").append(
        MessageItem(role=MessageRole.USER, text=text, media=media)
    )
    window = (manager or ContextWindowManager()).assemble(
        task=_task(), state=state, system_prompt="sys", skills_index="", tools=()
    )
    return window.chars


def test_constants_are_the_designed_estimates() -> None:
    assert IMAGE_TOKEN_ESTIMATE == 1_100
    assert AUDIO_TOKENS_PER_SECOND == 10


def test_an_image_counts_as_its_token_estimate() -> None:
    assert _chars(_image()) - _chars() == IMAGE_TOKEN_ESTIMATE * 4


def test_a_large_image_counts_by_its_size() -> None:
    """A large image costs more than the flat estimate (self-review 2.1): one token per
    750 bytes, so many large images push the window toward compaction."""
    size = 3_000_000
    assert _chars(_image(size)) - _chars() == math.ceil(size / 750) * 4


def test_transcribed_audio_counts_as_its_transcript() -> None:
    transcript = "what is in the photo I sent?"
    assert _chars(_audio(transcript=transcript)) - _chars() == len(transcript)


def test_native_audio_counts_by_its_duration() -> None:
    expected = math.ceil(2_500 / 1000 * AUDIO_TOKENS_PER_SECOND) * 4
    assert _chars(_audio()) - _chars() == expected


@pytest.mark.parametrize("rate", [1, 25])
def test_the_audio_rate_is_overridable(rate: int) -> None:
    manager = ContextWindowManager(audio_tokens_per_second=rate)
    expected = math.ceil(2_500 / 1000 * rate) * 4
    assert _chars(_audio(), manager=manager) - _chars(manager=manager) == expected


def test_native_audio_of_unknown_duration_counts_nothing_extra() -> None:
    assert _chars(_audio(duration_ms=None)) == _chars()


def test_media_pushes_a_window_over_budget() -> None:
    manager = ContextWindowManager(turn_budget_tokens=2_000)
    state = AgentState(task_id="t-1").append(
        MessageItem(role=MessageRole.USER, text="look", media=(_image(), _image()))
    )
    window = manager.assemble(
        task=_task(), state=state, system_prompt="sys", skills_index="", tools=()
    )
    info = LLMModelInfo(provider="fake", model="m", context_window_tokens=128_000)
    assert manager.over_budget(window, info)
