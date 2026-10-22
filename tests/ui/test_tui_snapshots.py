"""T5/T6: the TUI's states match the accepted snapshots (``--snapshot-update`` to accept)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path, PurePath
from typing import Any, Protocol

from a2a.types import Part, TaskState
from a2a.utils.errors import InvalidParamsError
from textual.app import App
from textual.pilot import Pilot
from textual.widgets import Input, ListView

from tests.fixtures import media as fx
from tests.ui.prototype import (
    AGENT_URL,
    COMMANDS,
    MEDIA_COMMANDS,
    MEDIA_PARAMS,
    TASK_ID,
    agent_image,
    agent_text,
    completed_events,
    conversation_events,
    echo,
    media_url,
    parked,
    prototype_events,
    speech,
    status,
    sub_task,
    sub_task_events,
    transcript,
    url_part,
)
from tests.unit.tui.fakes import FakeMicrophone, FakeSpeakers, tone
from tiny_harness.interaction.tui import EventSource, HarnessApp, ScriptedClient
from tiny_harness.interaction.tui.client import Attachment
from tiny_harness.interaction.tui.media import MediaCache
from tiny_harness.interaction.tui.voice import PcmPlayer, Recorder


class SnapCompare(Protocol):
    def __call__(
        self,
        app: str | PurePath | App[Any],
        press: tuple[str, ...] = (),
        terminal_size: tuple[int, int] = (80, 24),
        run_before: Callable[[Pilot[Any]], Awaitable[None] | None] | None = None,
    ) -> bool: ...


def app() -> HarnessApp:
    return HarnessApp(ScriptedClient(), url="http://localhost:8080", task_id=None)


async def feed(pilot: Pilot[Any]) -> None:
    assert isinstance(pilot.app, HarnessApp)
    pilot.app.feed(prototype_events())
    await pilot.pause()


def test_conversation_state(snap_compare: SnapCompare) -> None:
    assert snap_compare(app(), terminal_size=(110, 36), run_before=feed)


def test_plan_pane(snap_compare: SnapCompare) -> None:
    assert snap_compare(app(), terminal_size=(110, 36), press=("f2",), run_before=feed)


def test_trace_pane(snap_compare: SnapCompare) -> None:
    assert snap_compare(app(), terminal_size=(110, 36), press=("f2", "f2"), run_before=feed)


def test_empty_state(snap_compare: SnapCompare) -> None:
    assert snap_compare(app(), terminal_size=(110, 24))


def test_task_id_in_topbar() -> None:
    harness = app()
    harness.task_id = TASK_ID
    assert "7f3a…c21e" in harness.topbar_text()


# --- issue-25: the states of ``design/tui-task-controls.html`` ---------------------------


def controls_app() -> HarnessApp:
    client = ScriptedClient(scripts=[[sub_task()]], commands=COMMANDS, tasks=[sub_task()])
    return HarnessApp(client, url="http://localhost:8080", participant="alice")


async def conversation(pilot: Pilot[Any]) -> None:
    assert isinstance(pilot.app, HarnessApp)
    pilot.app.feed(conversation_events())
    await pilot.pause()


async def with_sub_task(pilot: Pilot[Any]) -> None:
    assert isinstance(pilot.app, HarnessApp)
    pilot.app.feed([*conversation_events(), *sub_task_events()])
    await pilot.app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
    await pilot.pause()


async def sub_task_open(pilot: Pilot[Any]) -> None:
    await with_sub_task(pilot)
    pilot.app.query_one("#sub-tasks", ListView).focus()
    await pilot.press("enter")
    await pilot.app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
    await pilot.pause()


async def completed(pilot: Pilot[Any]) -> None:
    assert isinstance(pilot.app, HarnessApp)
    pilot.app.feed([*conversation_events(), *completed_events()])
    await pilot.pause()


def test_input_required_with_sub_state(snap_compare: SnapCompare) -> None:
    assert snap_compare(controls_app(), terminal_size=(110, 36), run_before=conversation)


def test_slash_completion_and_hint(snap_compare: SnapCompare) -> None:
    assert snap_compare(
        controls_app(), terminal_size=(110, 36), press=("/", "s"), run_before=conversation
    )


def test_sub_task_row(snap_compare: SnapCompare) -> None:
    assert snap_compare(controls_app(), terminal_size=(110, 36), run_before=with_sub_task)


def test_sub_task_open(snap_compare: SnapCompare) -> None:
    assert snap_compare(controls_app(), terminal_size=(110, 36), run_before=sub_task_open)


def test_completed_state(snap_compare: SnapCompare) -> None:
    assert snap_compare(controls_app(), terminal_size=(110, 36), run_before=completed)


# --- issue-38: the states of ``design/tui-multimodal.html`` ------------------------------

MIB = 1024 * 1024


def media_app(tmp_path: Path, client: ScriptedClient) -> HarnessApp:
    cache = MediaCache(tmp_path, label="~/.cache/tiny-harness/media")
    return HarnessApp(client, url=AGENT_URL, participant="you", media_cache=cache)


def chip_files() -> list[Attachment]:
    return [
        Attachment("sofa-closeup.jpg", "image/jpeg", b"\0" * 940 * 1024, width=1600, height=1200),
        Attachment("note.m4a", "audio/mp4", b"\0" * 180_000, duration_ms=12_000),
    ]


def test_attachment_chips(snap_compare: SnapCompare, tmp_path: Path) -> None:
    """State 2: two chips above the composer, the count in the hint."""

    async def run_before(pilot: Pilot[Any]) -> None:
        assert isinstance(pilot.app, HarnessApp)
        pilot.app.feed(conversation_events())
        for attachment in chip_files():
            pilot.app.add_attachment(attachment)
        pilot.app.query_one("#composer", Input).value = "Which of these works with the rug idea?"
        await pilot.pause()

    client = ScriptedClient(commands=MEDIA_COMMANDS, media=MEDIA_PARAMS)
    assert snap_compare(media_app(tmp_path, client), terminal_size=(110, 36), run_before=run_before)


def test_image_fallback_line(snap_compare: SnapCompare, tmp_path: Path) -> None:
    """State 3: the user's image and audio, and the agent's image as the saved-to line."""
    photo = url_part("Ph7c", "image/jpeg", "sofa-closeup.jpg", width=1600, height=1200, size=962560)
    note = url_part("Au1", "audio/mp4", "note.m4a", durationMs=12_000, size=180_000)
    events = [
        *conversation_events(),
        echo(photo, note, Part(text="Which of these works with the rug idea?"), message_id="m-2"),
        status(TaskState.TASK_STATE_WORKING),
        status(
            TaskState.TASK_STATE_WORKING, agent_text("Here is a mock-up with a green sofa:", "a2")
        ),
        agent_image("Qm3xk2", "the room with a green sofa"),
        parked(),
    ]
    files = {
        media_url("Qm3xk2"): [fx.png(1024, 768)],
        media_url("Ph7c"): [fx.jpeg(1600, 1200)],
    }
    client = ScriptedClient(commands=MEDIA_COMMANDS, media=MEDIA_PARAMS, files=files)

    async def run_before(pilot: Pilot[Any]) -> None:
        assert isinstance(pilot.app, HarnessApp)
        pilot.app.feed(events)
        await pilot.app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

    assert snap_compare(media_app(tmp_path, client), terminal_size=(110, 36), run_before=run_before)


class Refusing(ScriptedClient):
    def send(
        self,
        parts: Sequence[Part],
        *,
        task_id: str | None,
        context_id: str,
        speak: bool = False,
    ) -> EventSource:
        super().send(parts, task_id=task_id, context_id=context_id, speak=speak)
        return self._refuse()

    async def _refuse(self) -> EventSource:
        raise InvalidParamsError(
            message="'holiday-video.webm' is larger than the 20971520-byte limit per file",
            data={"reason": "too_large", "limit": str(20 * MIB), "part": "0"},
        )
        yield


def test_attachment_rejected(snap_compare: SnapCompare, tmp_path: Path) -> None:
    """State 8: the server refused the file; the chip stays and the error names the limit."""

    async def run_before(pilot: Pilot[Any]) -> None:
        assert isinstance(pilot.app, HarnessApp)
        pilot.app.feed(conversation_events())
        clip = Attachment("holiday-video.webm", "audio/webm", b"\0" * 48 * MIB)
        pilot.app.add_attachment(clip)
        await pilot.press("enter")
        await pilot.app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()

    client = Refusing(commands=MEDIA_COMMANDS, media=MEDIA_PARAMS)
    assert snap_compare(media_app(tmp_path, client), terminal_size=(110, 36), run_before=run_before)


def voice_snapshot_app(
    tmp_path: Path, client: ScriptedClient
) -> tuple[HarnessApp, FakeMicrophone, FakeSpeakers]:
    mic, speakers = FakeMicrophone(), FakeSpeakers()
    app = HarnessApp(
        client,
        url=AGENT_URL,
        participant="you",
        media_cache=MediaCache(tmp_path, label="~/.cache/tiny-harness/media"),
        recorder=Recorder(open_input=mic),
        player=PcmPlayer(open_output=speakers),
    )
    return app, mic, speakers


def speaking_levels(seconds: float) -> bytes:
    """A voice-like signal: louder and quieter blocks, so the meter moves."""
    return b"".join(tone(0.1, amplitude=a) for a in (2000, 4000, 7000, 8000) * int(seconds * 2.5))


def test_recording_bar(snap_compare: SnapCompare, tmp_path: Path) -> None:
    """State 4: recording, with the level meter and the timer above the composer."""
    client = ScriptedClient(commands=MEDIA_COMMANDS, media=MEDIA_PARAMS)
    app, mic, _ = voice_snapshot_app(tmp_path, client)

    async def run_before(pilot: Pilot[Any]) -> None:
        assert isinstance(pilot.app, HarnessApp)
        pilot.app.feed(conversation_events())
        await pilot.press("f5")
        mic.stream.feed(speaking_levels(4.0), block=1600)
        await pilot.pause(0.15)

    assert snap_compare(app, terminal_size=(110, 36), run_before=run_before)


def test_voice_transcript(snap_compare: SnapCompare, tmp_path: Path) -> None:
    """State 5: the voice turn shows its transcript; the task works on it."""
    voice = url_part("Vo1", "audio/wav", "voice.wav", durationMs=4_000, voice=True, size=128_044)
    events = [
        *conversation_events(),
        echo(voice, message_id="m-3"),
        status(TaskState.TASK_STATE_WORKING),
        transcript("Vo1", "Would a rug work better than a throw on the sofa in the first photo?"),
    ]
    client = ScriptedClient(commands=MEDIA_COMMANDS, media=MEDIA_PARAMS)

    async def run_before(pilot: Pilot[Any]) -> None:
        assert isinstance(pilot.app, HarnessApp)
        pilot.app.feed(events)
        await pilot.pause()

    app, _, _ = voice_snapshot_app(tmp_path, client)
    assert snap_compare(app, terminal_size=(110, 36), run_before=run_before)


def test_speaking_line(snap_compare: SnapCompare, tmp_path: Path) -> None:
    """State 6: the reply is spoken as it streams; Escape stops it."""
    gate = asyncio.Event()
    reply = agent_text(
        "Yes — a 160 by 230 cm rug in rust under the front legs of the sofa warms the whole "
        "floor; a throw only changes the sofa.",
        "a-3",
    )
    pcm = speaking_levels(1.0)  # 16 kHz samples played as 24 kHz: 0:00 of 0:01, still streaming
    client = ScriptedClient(
        commands=MEDIA_COMMANDS, media=MEDIA_PARAMS, files={media_url("Sp1"): [pcm, gate]}
    )
    app, _, speakers = voice_snapshot_app(tmp_path, client)

    async def run_before(pilot: Pilot[Any]) -> None:
        assert isinstance(pilot.app, HarnessApp)
        pilot.app.feed(conversation_events())
        await pilot.press("f6")
        pilot.app.feed([speech("Sp1"), status(TaskState.TASK_STATE_WORKING, reply), parked()])
        for _ in range(50):
            if speakers.played == pcm:
                break
            await pilot.pause(0.02)
        await pilot.pause(0.15)

    assert snap_compare(app, terminal_size=(110, 36), run_before=run_before)
