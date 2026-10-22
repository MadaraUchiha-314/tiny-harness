"""T5/T9: every action of the TUI has a key (R20, accessibility row of the testing plan),
and issue-25's task controls: Complete/Cancel, the sub-state, ``/`` completion and
sub-task navigation (R5.5-R5.7, R6.7, R9.4)."""

from __future__ import annotations

import asyncio
import stat
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from a2a.types import Part, Task, TaskState, TaskStatusUpdateEvent
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
from google.protobuf import json_format
from textual.pilot import Pilot
from textual.widgets import Button, Input, ListView, Static, TabbedContent

from tests.fixtures import media as fx
from tests.ui.prototype import (
    AGENT_URL,
    COMMANDS,
    MEDIA_COMMANDS,
    MEDIA_PARAMS,
    SUB_TASK_ID,
    TASK_ID,
    agent_image,
    agent_text,
    completed_events,
    conversation_events,
    conversation_task,
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
from tests.unit.tui.fakes import FakeInput, FakeMicrophone, FakeSpeakers
from tests.unit.tui.fakes import tone as fx_tone
from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.core import TaskRef
from tiny_harness.interaction.tui import EventSource, HarnessApp, ScriptedClient
from tiny_harness.interaction.tui.a2ui import SurfaceView
from tiny_harness.interaction.tui.app import CHEVRON, Entry, SubTaskRow
from tiny_harness.interaction.tui.media import (
    NO_GRAPHICS,
    TIMES,
    AudioEntry,
    MediaCache,
    MediaEntry,
    SpeechEntry,
    human_size,
)
from tiny_harness.interaction.tui.voice import (
    INPUT_UNAVAILABLE,
    HoldDetector,
    PcmPlayer,
    Recorder,
    VoiceUnavailable,
    wav_pcm,
)


async def test_enter_sends_and_the_reply_streams_in() -> None:
    client = ScriptedClient(scripts=[prototype_events()])
    app = HarnessApp(client)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press(*"refund order 48213", "enter")
        await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
        await pilot.pause()
        assert client.sent == ["refund order 48213"]
        assert app.task_id == TASK_ID and app.state_name == "INPUT_REQUIRED"
        entries = [e.text for e in app.query(Entry)]
        assert any("help requested" in e for e in entries), entries
        placeholder = "unrenderable artifact part: application/vnd.example.calendar+json"
        assert any(placeholder in e for e in entries), entries
        assert len(app.query(SurfaceView)) == 1


async def test_f2_cycles_the_side_panes_and_tab_moves_focus() -> None:
    app = HarnessApp(ScriptedClient())
    async with app.run_test(size=(110, 36)) as pilot:
        side = app.query_one("#side", TabbedContent)
        assert side.active == "task"
        await pilot.press("f2")
        assert side.active == "plan"
        await pilot.press("f2", "f2")
        assert side.active == "task"
        assert isinstance(app.focused, Input)
        await pilot.press("tab")
        assert not isinstance(app.focused, Input)


async def test_a2ui_button_sends_the_action_with_the_chosen_value() -> None:
    client = ScriptedClient(scripts=[[status(TaskState.TASK_STATE_WORKING)]])
    app = HarnessApp(client, task_id=TASK_ID)
    async with app.run_test(size=(120, 60)) as pilot:
        app.feed(prototype_events())
        await pilot.pause()
        surface = app.query_one(SurfaceView)
        radios = surface.query_one("#a2ui-pick")
        radios.focus()
        await pilot.press("down", "enter")  # choose the second option
        await pilot.pause()
        surface.query_one("#a2ui-ok", Button).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert [a.name for a in client.actions] == ["confirm"]
        assert client.actions[0].source_component_id == "ok"
        assert client.actions[0].context == {"choice": ["refund"]}


async def test_ctrl_c_cancels_the_task_and_q_quits() -> None:
    client = ScriptedClient()
    app = HarnessApp(client, task_id=TASK_ID)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert client.cancelled == [TASK_ID]
        await pilot.press("tab", "q")
        await pilot.pause()
    assert app.return_code == 0 or app.return_code is None


# --- issue-25: task controls ----------------------------------------------------------


def entries(app: HarnessApp) -> list[str]:
    return [e.text for e in app.query(Entry)]


def static_text(app: HarnessApp, selector: str) -> str:
    return str(app.query_one(selector, Static).render())


async def settle(app: HarnessApp) -> None:
    await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]


async def test_the_top_bar_shows_the_state_and_the_sub_state() -> None:
    """R5.7: ``STATE · sub-state`` while INPUT_REQUIRED; an unknown sub-state is plain."""
    app = HarnessApp(ScriptedClient(commands=COMMANDS))
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.pause()
        assert "task 7f3a…c21e · INPUT_REQUIRED · awaiting-next-message" in app.topbar_text()
        assert app.sub_state == "awaiting-next-message"
        assert "── task → INPUT_REQUIRED · awaiting-next-message · your turn" in entries(app)
        app.feed([status(TaskState.TASK_STATE_WORKING)])
        await pilot.pause()
        assert app.topbar_text().endswith("task 7f3a…c21e · WORKING")
        app.feed([parked(sub_state="awaiting-something-new")])
        await pilot.pause()
        assert app.topbar_text().endswith("task 7f3a…c21e · INPUT_REQUIRED")


async def test_ctrl_d_completes_the_open_task() -> None:
    """R5.5: ``ctrl+d`` sends the control envelope; once terminal both controls refuse."""
    client = ScriptedClient(scripts=[completed_events()], commands=COMMANDS)
    app = HarnessApp(client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.pause()
        assert app.check_action("complete_task", ()) is True
        assert app.check_action("cancel_task", ()) is True
        await pilot.press("ctrl+d")
        await settle(app)
        await pilot.pause()
        assert client.completed == [TASK_ID]
        assert app.state_name == "COMPLETED"
        assert app.topbar_text().endswith("· COMPLETED")
        assert app.check_action("complete_task", ()) is None  # shown, disabled
        assert app.check_action("cancel_task", ()) is None
        await pilot.press("ctrl+d", "ctrl+c")
        await settle(app)
        await pilot.pause()
        assert client.completed == [TASK_ID] and client.cancelled == []
        assert entries(app).count("── already COMPLETED") == 2
        assert app.query_one("#composer", Input).value == ""


async def test_the_controls_need_an_open_task() -> None:
    client = ScriptedClient()
    app = HarnessApp(client)
    async with app.run_test(size=(110, 36)) as pilot:
        assert app.check_action("complete_task", ()) is None
        await pilot.press("ctrl+d", "ctrl+c")
        await pilot.pause()
        assert client.completed == [] and client.cancelled == []
        assert entries(app).count("── no task open") == 2


async def test_a_message_to_a_terminal_task_is_not_sent() -> None:
    client = ScriptedClient()
    app = HarnessApp(client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed([*conversation_events(), *completed_events()])
        await pilot.pause()
        await pilot.press(*"hello", "enter")
        await pilot.pause()
        assert client.sent == []
        assert "── task is COMPLETED; nothing sent" in entries(app)


async def test_a_refused_cancel_shows_the_reason() -> None:
    class Refusing(ScriptedClient):
        async def cancel(self, task_id: str) -> Task:
            raise UnsupportedOperationError(message="a watcher cannot cancel the task")

    app = HarnessApp(Refusing())
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.pause()
        await pilot.press("ctrl+c")
        await settle(app)
        await pilot.pause()
        assert "── a watcher cannot cancel the task" in entries(app)
        assert app.state_name == "INPUT_REQUIRED"


async def test_a_refused_completion_shows_the_reason() -> None:
    class Failing(ScriptedClient):
        def complete(self, task_id: str) -> EventSource:
            self.completed.append(task_id)
            return self._fail()

        async def _fail(self) -> EventSource:
            raise UnsupportedOperationError(
                message="the task is in a terminal state (TASK_STATE_CANCELED)"
            )
            yield  # an async generator, as the port's streams are

    failing = Failing()
    app = HarnessApp(failing)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.pause()
        await pilot.press("ctrl+d")
        await settle(app)
        await pilot.pause()
        assert failing.completed == [TASK_ID]
        assert "── the task is in a terminal state (TASK_STATE_CANCELED)" in entries(app)


async def test_slash_suggests_commands_and_the_hint_lists_them() -> None:
    """R6.7: the card's commands complete inline; the hint line describes the matches."""
    app = HarnessApp(ScriptedClient(commands=COMMANDS))
    async with app.run_test(size=(110, 36)) as pilot:
        composer = app.query_one("#composer", Input)
        await pilot.press("/")
        hint = static_text(app, "#hint")
        for spec in COMMANDS:
            assert f"/{spec.name}" in hint and spec.description in hint, hint
        assert "[name]" in hint and "<description>" in hint
        await pilot.press("s")
        hint = static_text(app, "#hint")
        assert "/status" in hint and "/sub-task" in hint and "/model" not in hint
        await pilot.press("u")
        assert composer._suggestion == "/sub-task"  # pyright: ignore[reportPrivateUsage]
        await pilot.press("right")
        assert composer.value == "/sub-task"
        await pilot.press("space", *"x")
        assert static_text(app, "#hint") == ""
        composer.value = "hello"
        await pilot.pause()
        assert static_text(app, "#hint") == ""


async def test_sub_task_reply_adds_a_row_enter_opens_it_and_f4_returns() -> None:
    """R9.4: ``/sub-task`` replies with the id and a row; Enter opens it, F4 goes back."""
    client = ScriptedClient(
        scripts=[sub_task_events()],
        commands=COMMANDS,
        tasks=[sub_task()],
        follow={SUB_TASK_ID: [sub_task()]},
    )
    app = HarnessApp(client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.pause()
        assert app.check_action("parent_task", ()) is None
        await pilot.press(*"/sub-task Draft the reply", "enter")
        await settle(app)
        await pilot.pause()
        assert client.sent == ["/sub-task Draft the reply"]
        assert f"⌘ Created sub-task {SUB_TASK_ID}." in entries(app)
        # The row's state comes from the parent's stream; the sub-task is read once for
        # its goal and followed only once opened (R5.6).
        assert client.subscribed == [TASK_ID] and client.fetched == [SUB_TASK_ID]
        rows = list(app.query(SubTaskRow))
        assert [r.ref.task_id for r in rows] == [SUB_TASK_ID]
        assert rows[0].text == "9b21…d4e5 · INPUT_REQUIRED · Draft the reply"
        app.query_one("#sub-tasks", ListView).focus()
        await pilot.press("enter")
        await settle(app)
        await pilot.pause()
        assert app.task_id == SUB_TASK_ID and app.stack == [TASK_ID, SUB_TASK_ID]
        assert client.subscribed == [TASK_ID, SUB_TASK_ID]
        assert f"7f3a…c21e {CHEVRON} task 9b21…d4e5 · INPUT_REQUIRED" in app.topbar_text()
        assert app.ext is not None and app.ext.goal == "Draft the reply"
        assert app.check_action("parent_task", ()) is True
        assert "── task → INPUT_REQUIRED · awaiting-next-message · your turn" in [
            e.text for e in app.query(Entry) if e.display
        ]
        assert f"⌘ Created sub-task {SUB_TASK_ID}." not in [
            e.text for e in app.query(Entry) if e.display
        ]
        await pilot.press("f4")
        await pilot.pause()
        assert app.task_id == TASK_ID and app.stack == [TASK_ID]
        assert f"⌘ Created sub-task {SUB_TASK_ID}." in [
            e.text for e in app.query(Entry) if e.display
        ]
        assert app.ext is not None and app.ext.goal.startswith("Summarise")
        assert app.check_action("parent_task", ()) is None


async def test_a_remote_sub_task_does_not_open_here() -> None:
    from tiny_harness.harness.entities import EntityKind, EntityRef

    remote = TaskRef(task_id="t-91a0", agent=EntityRef(kind=EntityKind.AGENT, id="billing-agent"))
    client = ScriptedClient()
    app = HarnessApp(client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(prototype_events())
        await pilot.pause()
        rows = list(app.query(SubTaskRow))
        assert [r.ref for r in rows] == [remote]
        assert rows[0].text == "billing-agent/t-91a0 · — · —"
        app.query_one("#sub-tasks", ListView).focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.task_id == TASK_ID and client.subscribed == []
        assert "t-91a0" not in client.fetched
        assert "── sub-task t-91a0 is on billing-agent; open it there" in entries(app)


async def test_a_sub_task_that_cannot_be_followed_is_fetched_once() -> None:
    """A terminal task refuses ``SubscribeToTask``; opening it falls back to ``GetTask``,
    and a task that has ended is not followed again."""
    done = sub_task()
    done.status.state = TaskState.TASK_STATE_COMPLETED

    class Refusing(ScriptedClient):
        def subscribe(self, task_id: str) -> EventSource:
            self.subscribed.append(task_id)
            return self._fail()

        async def _fail(self) -> EventSource:
            raise UnsupportedOperationError(message="task is in a terminal state")
            yield  # an async generator, as the port's streams are

    client = Refusing(tasks=[done])
    app = HarnessApp(client, resubscribe_delay=0.01)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        app.open_sub_task(TaskRef(task_id=SUB_TASK_ID))
        await settle(app)
        await pilot.pause(0.1)
        assert client.subscribed == [SUB_TASK_ID] and client.fetched == [SUB_TASK_ID]
        assert app.state_name == "COMPLETED"


async def test_another_surface_completing_the_task_shows_without_a_reload() -> None:
    """R5.6: a COMPLETED update on the subscription stream ends the controls."""
    client = ScriptedClient(follow={TASK_ID: [*conversation_events(), *completed_events()]})
    app = HarnessApp(client, task_id=TASK_ID)
    async with app.run_test(size=(110, 36)) as pilot:
        await settle(app)
        await pilot.pause()
        assert client.subscribed == [TASK_ID]
        assert app.state_name == "COMPLETED"
        assert app.check_action("complete_task", ()) is None


async def test_cancel_applies_the_canceled_task() -> None:
    client = ScriptedClient()
    app = HarnessApp(client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.pause()
        await pilot.press("ctrl+c")
        await settle(app)
        await pilot.pause()
        assert client.cancelled == [TASK_ID]
        assert app.state_name == "CANCELED"
        assert app.ext is not None  # a bare Task keeps what the TUI knew


async def test_sub_task_rows_follow_the_parent_stream_without_polling() -> None:
    """R5.6: after a message's stream parks, the TUI follows the task's own stream; a
    sub-task's row changes when the parent relays its state, with no sub-task followed
    and nothing re-read on a timer."""
    release = asyncio.Event()
    working = conversation_task((TaskRef(task_id=SUB_TASK_ID, state="WORKING"),))

    class Following(ScriptedClient):
        def subscribe(self, task_id: str) -> EventSource:
            self.subscribed.append(task_id)
            return self._follow()

        async def _follow(self) -> EventSource:
            await release.wait()
            yield working
            await asyncio.Event().wait()  # stays open, as SubscribeToTask does

    client = Following(scripts=[sub_task_events()], tasks=[sub_task()])
    app = HarnessApp(client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        app.query_one("#composer", Input).value = "/sub-task Draft the reply"
        await pilot.press("enter")
        await until_fetched(pilot, client, SUB_TASK_ID)
        [row] = app.query(SubTaskRow)
        assert row.text == "9b21…d4e5 · INPUT_REQUIRED · Draft the reply"
        assert client.subscribed == [TASK_ID]
        release.set()
        await until_row(pilot, row, "9b21…d4e5 · WORKING · Draft the reply")
        assert client.subscribed == [TASK_ID] and client.fetched == [SUB_TASK_ID]


async def test_a_replayed_status_draws_nothing_new() -> None:
    """``SubscribeToTask`` replays the log from the start: states the TUI already drew
    from the message's own stream are not drawn again, nor rolled back."""
    from google.protobuf.timestamp_pb2 import Timestamp

    def stamped(state: TaskState, seconds: int) -> TaskStatusUpdateEvent:
        event = status(state)
        event.status.timestamp.CopyFrom(Timestamp(seconds=seconds))
        return event

    log = [
        stamped(TaskState.TASK_STATE_WORKING, 1),
        stamped(TaskState.TASK_STATE_INPUT_REQUIRED, 2),
    ]
    app = HarnessApp(ScriptedClient())
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        app.feed(log)
        await pilot.pause()
        before = entries(app)
        app.feed(log)  # the replay
        await pilot.pause()
        assert entries(app) == before
        assert app.state_name == "INPUT_REQUIRED"


async def until_row(pilot: Pilot[None], row: SubTaskRow, text: str) -> None:
    for _ in range(100):
        if row.text == text:
            return
        await pilot.pause(0.02)
    raise AssertionError(f"the row never read {text!r}: {row.text!r}")


async def until_fetched(pilot: Pilot[None], client: ScriptedClient, task_id: str) -> None:
    for _ in range(100):
        if task_id in client.fetched:
            return
        await pilot.pause(0.02)
    raise AssertionError(f"{task_id} was never fetched: {client.fetched}")


# --- issue-38: /attach, chips and media entries (T5) -----------------------------------


def media_app(tmp_path: Path, client: ScriptedClient, **kwargs: Any) -> HarnessApp:
    cache = MediaCache(tmp_path / "cache", label="~/.cache/tiny-harness/media")
    return HarnessApp(client, url=AGENT_URL, media_cache=cache, **kwargs)


def media_client(*scripts: list[A2AEvent], **kwargs: Any) -> ScriptedClient:
    return ScriptedClient(
        scripts=list(scripts), commands=MEDIA_COMMANDS, media=MEDIA_PARAMS, **kwargs
    )


def chips(app: HarnessApp) -> str:
    return static_text(app, "#chips")


async def type_line(pilot: Pilot[None], app: HarnessApp, text: str) -> None:
    app.query_one("#composer", Input).value = text
    await pilot.press("enter")
    await settle(app)
    await pilot.pause()


async def test_attach_adds_a_chip_and_enter_sends_the_file(tmp_path: Path) -> None:
    photo = tmp_path / "sofa.png"
    photo.write_bytes(fx.png(1024, 768))
    client = media_client([*conversation_events()])
    app = media_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        await type_line(pilot, app, f"/attach {photo}")
        assert client.sent == []  # a surface command runs here and sends nothing
        assert "[image] sofa.png ·" in chips(app)
        assert app.query_one("#chips").display
        assert static_text(app, "#hint") == "Enter sends the message with 1 attachment"
        await type_line(pilot, app, "Which works?")
        assert client.sent == ["Which works?"]
        [parts] = client.sent_parts
        assert parts[0].text == "Which works?"
        assert parts[1].raw == photo.read_bytes()
        assert (parts[1].media_type, parts[1].filename) == ("image/png", "sofa.png")
        assert not app.query_one("#chips").display and app.attachments == []
        lines = entries(app) + [e.text for e in app.query(MediaEntry)]
        assert any(t.startswith(f"you {CHEVRON} [image] sofa.png · 1024{TIMES}768") for t in lines)
        assert "      Which works?" in lines


async def test_attach_runs_only_when_the_card_lists_it(tmp_path: Path) -> None:
    """The client implements no command of its own: without ``attach`` on the card the
    text goes to the agent like any message."""
    client = ScriptedClient(scripts=[[]], commands=COMMANDS, media=MEDIA_PARAMS)
    app = media_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        await type_line(pilot, app, f"/attach {tmp_path}/x.png")
        assert client.sent == [f"/attach {tmp_path}/x.png"]
        assert app.attachments == []


async def test_attach_refuses_what_the_card_does_not_accept(tmp_path: Path) -> None:
    svg = tmp_path / "logo.png"
    svg.write_bytes(fx.SVG)
    big = tmp_path / "big.png"
    big.write_bytes(fx.png(4, 4, padding=4096))
    small = MEDIA_PARAMS.model_copy(update={"max_file_bytes": 1024})
    client = ScriptedClient(commands=MEDIA_COMMANDS, media=small)
    app = media_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        await type_line(pilot, app, f"/attach {svg}")
        await type_line(pilot, app, f"/attach {big}")
        await type_line(pilot, app, f"/attach {tmp_path}/missing.png")
        await type_line(pilot, app, "/attach")
        assert app.attachments == [] and client.sent == []
        lines = entries(app)
        assert any(t.startswith("✗ not attached: logo.png is not a file this agent") for t in lines)
        assert "✗ not attached: big.png is 4 KB; the limit is 1024 bytes per file" in lines
        assert any(t.startswith("✗ not attached: missing.png:") for t in lines)
        assert "── usage: /attach <path>" in lines


async def test_attach_backspace_on_empty_composer_removes_the_last_chip(tmp_path: Path) -> None:
    for name in ("a.png", "b.wav"):
        (tmp_path / name).write_bytes(fx.png() if name.endswith("png") else fx.wav(2.0))
    app = media_app(tmp_path, media_client())
    async with app.run_test(size=(110, 36)) as pilot:
        await type_line(pilot, app, f"/attach {tmp_path}/a.png")
        await type_line(pilot, app, f"/attach {tmp_path}/b.wav")
        assert [a.name for a in app.attachments] == ["a.png", "b.wav"]
        assert "[audio] b.wav · 0:02" in chips(app)
        composer = app.query_one("#composer", Input)
        await pilot.press("x", "backspace")  # deletes the character, not a chip
        assert composer.value == "" and len(app.attachments) == 2
        await pilot.press("backspace")
        assert [a.name for a in app.attachments] == ["a.png"]
        await pilot.press("backspace", "backspace")
        assert app.attachments == [] and not app.query_one("#chips").display


async def test_attach_tab_completes_the_path(tmp_path: Path) -> None:
    (tmp_path / "pictures").mkdir()
    (tmp_path / "pictures" / "sofa-closeup.png").write_bytes(fx.png())
    app = media_app(tmp_path, media_client())
    async with app.run_test(size=(110, 36)) as pilot:
        composer = app.query_one("#composer", Input)
        composer.value = f"/attach {tmp_path}/pic"
        await pilot.pause(0.05)
        assert "Tab completes the path" in static_text(app, "#hint")
        await pilot.press("tab")
        assert composer.value == f"/attach {tmp_path}/pictures/"
        await pilot.press("s")
        await pilot.pause(0.05)
        await pilot.press("tab")
        assert composer.value == f"/attach {tmp_path}/pictures/sofa-closeup.png"
        assert isinstance(app.focused, Input)  # completing never moved focus


async def test_attach_rejected_by_the_server_keeps_the_chips(tmp_path: Path) -> None:
    """R1.3: the server's refusal names the file and the limit; nothing is shown as sent,
    and the chips and the text come back so a file can be removed."""

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
                message="'clip.webm' is larger than the 20971520-byte limit per file",
                data={"reason": "too_large", "limit": "20971520", "part": "1"},
            )
            yield

    clip = tmp_path / "clip.webm"
    clip.write_bytes(fx.webm())
    app = media_app(tmp_path, Refusing(commands=MEDIA_COMMANDS, media=MEDIA_PARAMS))
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await type_line(pilot, app, f"/attach {clip}")
        await type_line(pilot, app, "Is this the sofa?")
        size = human_size(len(fx.webm()))
        assert (
            f"✗ not sent: clip.webm is {size}; the limit is 20 MiB per file. Backspace removes it."
        ) in entries(app)
        assert [a.name for a in app.attachments] == ["clip.webm"]
        assert app.query_one("#composer", Input).value == "Is this the sofa?"
        assert not any("Is this the sofa?" in t for t in entries(app))
        assert list(app.query(AudioEntry)) == []


async def test_attach_echo_stores_the_own_image_without_fetching_it(tmp_path: Path) -> None:
    photo = tmp_path / "sofa.png"
    photo.write_bytes(fx.png(1024, 768))
    stored = url_part("Qm3xk2", "image/png", "sofa.png", width=1024, height=768)
    client = media_client([*conversation_events(), echo(Part(text="Which?"), stored)])
    app = media_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        await type_line(pilot, app, f"/attach {photo}")
        await type_line(pilot, app, "Which?")
        await settle(app)
        await pilot.pause()
        assert client.media_fetched == []  # the user's own bytes were cached
        cached = tmp_path / "cache" / TASK_ID / "Qm3xk2.png"
        assert cached.read_bytes() == photo.read_bytes()
        assert stat.S_IMODE(cached.stat().st_mode) == 0o600
        assert stat.S_IMODE(cached.parent.stat().st_mode) == 0o700
        [entry] = app.query(MediaEntry)
        assert entry.ids == (TASK_ID, "Qm3xk2")
        assert "saved to" not in entry.text  # the user has the file


async def test_attach_agent_image_shows_the_fallback_line(tmp_path: Path) -> None:
    """R2.4: no graphics protocol: one line naming the image and where it was saved."""
    image = fx.png(1024, 768)
    client = media_client(files={media_url("Im9a1"): [image[:10], image[10:]]})
    app = media_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed([*conversation_events(), agent_image("Im9a1", "the green sofa")])
        await settle(app)
        await pilot.pause()
        assert client.media_fetched == [media_url("Im9a1")]
        assert (tmp_path / "cache" / TASK_ID / "Im9a1.png").read_bytes() == image
        [entry] = app.query(MediaEntry)
        expected = (
            f"image · generated.png · 1024{TIMES}768 · saved to "
            "~/.cache/tiny-harness/media/7f3a…1e/Im9a1.png\n"
            f"{NO_GRAPHICS}"
        )
        assert entry.text == expected


async def test_attach_agent_image_draws_inline_with_graphics(tmp_path: Path) -> None:
    client = media_client(files={media_url("Im9a1"): [fx.png(1024, 768)]})
    shown: list[Path] = []

    def view(path: Path) -> Static:
        shown.append(path)
        return Static("[picture]", markup=False)

    app = media_app(tmp_path, client, image_view=view)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed([*conversation_events(), agent_image("Im9a1", "the green sofa")])
        await settle(app)
        await pilot.pause()
        assert shown == [tmp_path / "cache" / TASK_ID / "Im9a1.png"]
        [entry] = app.query(MediaEntry)
        assert entry.text == f"image · generated.png · 1024{TIMES}768"


async def test_attach_a_missing_medium_names_the_file(tmp_path: Path) -> None:
    app = media_app(tmp_path, media_client())
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed([*conversation_events(), agent_image("Gone1", "gone")])
        await settle(app)
        await pilot.pause()
        [entry] = app.query(MediaEntry)
        assert entry.text.startswith("image · generated.png · unavailable (")


async def test_attach_audio_and_another_participants_echo(tmp_path: Path) -> None:
    """R6.3: another participant's files show under their name; a voice turn shows its
    transcript once it arrives, also when the transcript comes first."""
    note = url_part("Au1", "audio/mp4", "note.m4a", durationMs=12_000, size=9000)
    voice = url_part("Vo1", "audio/webm", "voice.webm", durationMs=4_000, voice=True)
    app = media_app(tmp_path, media_client())
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        app.feed([echo(note, Part(text="hear this"), participant="bob", message_id="m-b")])
        app.feed([transcript("Vo1", "Would a rug work better?")])
        app.feed([echo(voice, participant="bob", message_id="m-b2")])
        app.feed([echo(note, participant="bob", message_id="m-b")])  # a replay: drawn once
        await pilot.pause()
        audio = [e.text for e in app.query(AudioEntry)]
        assert audio == [
            f"bob {CHEVRON} [audio] note.m4a · 0:12 · ⏎ to play",
            f"bob {CHEVRON} [voice] 0:04 · “Would a rug work better?”",
        ]
        assert "      hear this" in entries(app)
        assert not any("agent" in t and "hear this" in t for t in entries(app))


# --- issue-38: voice (T5): hold Space, F5, F6, Escape, with a fake clock and devices -----


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def voice_app(
    tmp_path: Path, client: ScriptedClient, **kwargs: Any
) -> tuple[HarnessApp, Clock, FakeMicrophone, FakeSpeakers]:
    clock, mic, speakers = Clock(), FakeMicrophone(), FakeSpeakers()
    app = media_app(
        tmp_path,
        client,
        recorder=Recorder(open_input=mic),
        player=PcmPlayer(open_output=speakers),
        hold=HoldDetector(clock=clock),
        **kwargs,
    )
    return app, clock, mic, speakers


async def at(pilot: Pilot[None], clock: Clock, when: float) -> None:
    """Move the fake clock and let the voice timer see it."""
    clock.now = when
    await pilot.pause(0.12)


async def test_voice_hold_space_records_and_release_sends(tmp_path: Path) -> None:
    """R3.2: Space held on an empty composer records; the end of the auto-repeat sends."""
    client = media_client([*conversation_events()])
    app, clock, mic, _ = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("space")
        assert app.query_one("#composer", Input).value == "" and not mic.opened
        clock.now = 0.45
        await pilot.press("space")  # the terminal's first auto-repeat
        await pilot.pause()
        assert app.recording == "hold" and mic.stream.started
        mic.stream.feed(fx_tone(2.0))
        for when in (0.5, 0.55, 0.6):
            clock.now = when
            await pilot.press("space")
        await at(pilot, clock, 0.7)
        assert static_text(app, "#rec").startswith("● REC  ")
        assert static_text(app, "#rec").endswith("  0:02")
        assert static_text(app, "#hint") == "release Space to send · Esc discards"
        await at(pilot, clock, 0.9)  # repeats stopped 0.3 s ago: released
        await settle(app)
        await pilot.pause()
        assert app.recording is None and mic.stream.closed
        assert not app.query_one("#rec").display
        [parts] = client.sent_parts
        [voice] = parts
        assert (voice.media_type, voice.filename) == ("audio/wav", "voice.wav")
        assert json_format.MessageToDict(voice.metadata) == {"voice": True, "durationMs": 2000}
        assert [e.text for e in app.query(AudioEntry)] == [
            f"you {CHEVRON} [voice] 0:02 · transcribing…"
        ]


async def test_voice_a_lone_space_is_typed(tmp_path: Path) -> None:
    app, clock, mic, _ = voice_app(tmp_path, media_client())
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("space")
        await at(pilot, clock, 0.7)
        composer = app.query_one("#composer", Input)
        assert composer.value == " " and not mic.opened
        await pilot.press("space", "x")  # spaces inside text are never held back
        assert composer.value == "  x"


async def test_voice_f5_toggles_and_a_short_recording_is_discarded(tmp_path: Path) -> None:
    """R3.3, R3.6."""
    client = media_client()
    app, _, mic, _ = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("f5")
        assert app.recording == "toggle"
        assert static_text(app, "#hint") == "F5 to send · Esc discards"
        mic.stream.feed(fx_tone(0.2))
        await pilot.press("f5")
        await pilot.pause()
        assert client.sent == [] and mic.stream.closed
        assert "── nothing recorded (too short or silent)" in entries(app)


async def test_voice_escape_discards_a_recording(tmp_path: Path) -> None:
    client = media_client()
    app, _, mic, _ = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("f5")
        mic.stream.feed(fx_tone(1.0))
        assert app.check_action("stop_voice", ()) is True
        await pilot.press("escape")
        await pilot.pause()
        assert app.recording is None and mic.stream.closed and client.sent == []
        assert "── recording discarded" in entries(app)


async def test_voice_quitting_while_recording_closes_the_microphone(tmp_path: Path) -> None:
    """Quitting with a recording open discards it and closes the microphone; a voice tick
    that lands while the app shuts down (its widgets already gone) does nothing."""
    client = media_client()
    app, _, mic, _ = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("f5")
        mic.stream.feed(fx_tone(1.0))
        assert app.recording == "toggle"
    assert app.recording is None and mic.stream.closed and client.sent == []
    app.recording = "toggle"  # as if the tick ran before the recording was discarded
    app._voice_tick()  # pyright: ignore[reportPrivateUsage]


async def test_voice_without_portaudio_names_the_extra_and_typing_works(tmp_path: Path) -> None:
    """R3.5."""

    def no_portaudio(rate: int, on_audio: Callable[[bytes], None]) -> FakeInput:
        raise VoiceUnavailable(INPUT_UNAVAILABLE)

    client = media_client([])
    app = media_app(tmp_path, client, recorder=Recorder(open_input=no_portaudio))
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        assert f"── {INPUT_UNAVAILABLE}" in entries(app)
        assert app.recording is None
        await pilot.press(*"hello", "enter")
        await settle(app)
        assert client.sent == ["hello"]


async def test_voice_controls_hide_without_media(tmp_path: Path) -> None:
    app = media_app(tmp_path, ScriptedClient())
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("space")
        assert app.query_one("#composer", Input).value == " "
        assert app.check_action("toggle_record", ()) is False
        assert app.check_action("toggle_speak", ()) is False
        assert "spoken replies" not in app.topbar_text()


async def test_voice_f6_speaks_replies_and_escape_stops_them(tmp_path: Path) -> None:
    """R4.1, R4.4: F6 sends ``speak``; the reply plays as it streams; Escape stops it."""
    gate = asyncio.Event()
    pcm = fx_tone(0.5, rate=24_000)
    reply = agent_text("A rust rug warms the floor.", "a-1")
    client = media_client(
        [speech("Sp1"), status(TaskState.TASK_STATE_WORKING, reply), parked()],
        files={media_url("Sp1"): [pcm, gate]},
    )
    app, _, _, speakers = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.press("f6")
        assert "🔈 spoken replies: on (F6)" in app.topbar_text()
        await pilot.press(*"rug?", "enter")
        for _ in range(50):
            if speakers.played == pcm:
                break
            await pilot.pause(0.02)
        assert client.spoken == [True]
        assert speakers.played == pcm
        [line] = app.query(SpeechEntry)
        await pilot.pause(0.12)
        assert line.text.startswith("🔊 speaking ") and line.text.endswith("0:00 / streaming")
        assert static_text(app, "#hint") == "speaking… Esc stops"
        conversation = [w for w in app.query_one("#conversation").children if w.display]
        texts = [getattr(w, "text", "") for w in conversation]
        assert texts.index(line.text) == texts.index(f"agent {CHEVRON} {reply.parts[0].text}") + 1
        await pilot.press("escape")
        gate.set()
        await settle(app)
        await pilot.pause()
        assert line.text == "🔊 stopped at 0:00 · ⏎ replays"


async def _speaking(pilot: Any, app: Any, client: Any, speakers: Any, pcm: bytes) -> Any:
    """F6 on, a message sent, and the reply streaming to the speakers: the speech line."""
    app.feed(conversation_events())
    await pilot.press("f6")
    await pilot.press(*"rug?", "enter")
    for _ in range(50):
        if speakers.played == pcm:
            break
        await pilot.pause(0.02)
    [line] = app.query(SpeechEntry)
    assert app.player.playing
    return line


@pytest.mark.parametrize("act", ["record", "send"])
async def test_voice_a_new_recording_or_message_stops_the_reply(tmp_path: Path, act: str) -> None:
    """R4.3: starting a recording (F5) or sending a message stops the reply being spoken."""
    gate = asyncio.Event()
    pcm = fx_tone(0.5, rate=24_000)
    reply = agent_text("A rust rug warms the floor.", "a-1")
    client = media_client(
        [speech("Sp1"), status(TaskState.TASK_STATE_WORKING, reply), parked()],
        files={media_url("Sp1"): [pcm, gate]},
    )
    app, _, _, speakers = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        line = await _speaking(pilot, app, client, speakers, pcm)
        if act == "record":
            await pilot.press("f5")
        else:
            await pilot.press(*"and the lamp?", "enter")
        gate.set()
        await settle(app)
        await pilot.pause()
        assert not app.player.playing
        assert line.text == "🔊 stopped at 0:00 · ⏎ replays"


async def test_voice_an_interrupted_reply_offers_replay(tmp_path: Path) -> None:
    """R4.3: a broken stream is "interrupted"; Enter on the line requests the URL again."""
    broken = httpx.RemoteProtocolError("peer closed connection without sending complete body")
    client = media_client(files={media_url("Sp2"): [fx_tone(0.25, rate=24_000), broken]})
    app, _, _, _ = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.press("f6")
        app.feed([speech("Sp2")])
        await settle(app)
        await pilot.pause()
        [line] = app.query(SpeechEntry)
        assert line.text == "🔊 speech interrupted · ⏎ replays"
        line.focus()
        await pilot.press("enter")
        await settle(app)
        assert client.media_fetched == [media_url("Sp2"), media_url("Sp2")]


async def test_voice_a_spoken_reply_waits_when_spoken_replies_are_off(tmp_path: Path) -> None:
    client = media_client(files={media_url("Sp3"): [fx_tone(0.25, rate=24_000)]})
    app, _, _, speakers = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed([*conversation_events(), speech("Sp3")])
        await settle(app)
        [line] = app.query(SpeechEntry)
        assert line.text == "🔊 spoken reply · ⏎ to play" and client.media_fetched == []
        line.focus()
        await pilot.press("enter")
        await settle(app)
        await pilot.pause()
        assert line.text == "🔊 spoken · 0:00 · ⏎ replays" and speakers.played


async def test_voice_enter_on_a_wav_entry_plays_it(tmp_path: Path) -> None:
    wav = fx.wav(0.5)
    (tmp_path / "note.wav").write_bytes(wav)
    app, _, _, speakers = voice_app(tmp_path, media_client([]))
    async with app.run_test(size=(110, 36)) as pilot:
        await type_line(pilot, app, f"/attach {tmp_path}/note.wav")
        await type_line(pilot, app, "listen")
        [entry] = app.query(AudioEntry)
        entry.focus()
        await pilot.press("enter")
        await settle(app)
        assert speakers.played == wav_pcm(wav)[0]


async def test_voice_a_replayed_speech_or_image_is_drawn_and_played_once(tmp_path: Path) -> None:
    """The task's subscription replays the log the send stream already showed: an image
    and a spoken reply are each drawn once, and the reply plays once."""
    pcm = fx_tone(0.25, rate=24_000)
    reply = agent_text("A rust rug warms the floor.", "a-1")
    turn: list[A2AEvent] = [
        speech("Sp1"),
        agent_image("Im9a1", "the green sofa"),
        status(TaskState.TASK_STATE_WORKING, reply),
        parked(),
    ]
    client = media_client(
        turn,
        files={media_url("Sp1"): [pcm], media_url("Im9a1"): [fx.png(1024, 768)]},
        follow={TASK_ID: [*conversation_events(), *turn]},
    )
    app, _, _, speakers = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        app.feed(conversation_events())
        await pilot.press("f6")
        await pilot.press(*"rug?", "enter")
        await settle(app)
        await pilot.pause()
        await settle(app)
        assert client.subscribed == [TASK_ID]
        assert len(app.query(SpeechEntry)) == 1
        assert len(app.query(MediaEntry)) == 1
        assert client.media_fetched.count(media_url("Sp1")) == 1
        assert speakers.played == pcm


async def test_voice_replay_during_playback_then_escape_stops(tmp_path: Path) -> None:
    """R4.3: Enter replays the reply while it plays: the first playback stops, only the
    replay plays, and Escape stops the replay."""
    gate = asyncio.Event()
    pcm = fx_tone(0.5, rate=24_000)
    reply = agent_text("A rust rug warms the floor.", "a-1")
    client = media_client(
        [speech("Sp1"), status(TaskState.TASK_STATE_WORKING, reply), parked()],
        files={media_url("Sp1"): [pcm, gate]},
    )
    app, _, _, speakers = voice_app(tmp_path, client)
    async with app.run_test(size=(110, 36)) as pilot:
        line = await _speaking(pilot, app, client, speakers, pcm)
        line.focus()
        await pilot.press("enter")
        for _ in range(50):
            if speakers.played == pcm + pcm:
                break
            await pilot.pause(0.02)
        assert speakers.opened[0].closed and len(speakers.opened) == 2
        assert app.player.playing
        await pilot.press("escape")
        await pilot.pause(0.12)
        assert not app.player.playing
        assert speakers.opened[1].closed
        assert line.text == "🔊 stopped at 0:00 · ⏎ replays"
        gate.set()
        await settle(app)
        await pilot.pause()
        assert speakers.played == pcm + pcm


class ClosingClient(ScriptedClient):
    """Counts the media streams closed before their end. It keeps every stream it made,
    so only an explicit ``aclose`` (not the garbage collector) closes one."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.closed: list[str] = []
        self.streams: list[object] = []

    def get_media(self, url: str) -> Any:
        stream = self._closing(url)
        self.streams.append(stream)
        return stream

    async def _closing(self, url: str) -> Any:
        try:
            async for chunk in ScriptedClient.get_media(self, url):
                yield chunk
        except GeneratorExit:
            self.closed.append(url)
            raise


async def test_a_download_over_the_limit_closes_the_media_stream(tmp_path: Path) -> None:
    client = ClosingClient(
        commands=MEDIA_COMMANDS,
        media=MEDIA_PARAMS.model_copy(update={"max_file_bytes": 1500}),
        files={media_url("Big1"): [b"\x00" * 1024] * 3},
    )
    app = media_app(tmp_path, client)
    async with app.run_test(size=(110, 36)):
        with pytest.raises(ValueError, match="larger than 1500 bytes"):
            await app._download(media_url("Big1"))  # pyright: ignore[reportPrivateUsage]
        assert client.closed == [media_url("Big1")]


async def test_voice_a_reply_stopped_mid_stream_closes_the_media_stream(tmp_path: Path) -> None:
    """Escape between two chunks: the player stops reading, and the stream it read from
    is closed at once."""
    block = fx_tone(0.1, rate=24_000)
    client = ClosingClient(
        commands=MEDIA_COMMANDS,
        media=MEDIA_PARAMS,
        files={media_url("Sp1"): [block, block, block]},
    )
    speakers = FakeSpeakers()
    player = PcmPlayer(open_output=speakers)
    app = media_app(tmp_path, client, player=player)

    async with app.run_test(size=(110, 36)) as pilot:
        loop = asyncio.get_running_loop()
        real = speakers.__call__

        def opening(fmt: Any) -> Any:
            stream = real(fmt)
            original = stream.write

            def write(data: bytes) -> None:
                original(data)
                loop.call_soon_threadsafe(player.stop)  # Escape after the first block

            stream.write = write  # type: ignore[method-assign]
            return stream

        player.open_output = opening
        app.feed(conversation_events())
        await pilot.press("f6")
        app.feed([speech("Sp1")])
        await settle(app)
        await pilot.pause()
        [line] = app.query(SpeechEntry)
        assert line.text == "🔊 stopped at 0:00 · ⏎ replays"
        assert speakers.played == block
        assert client.closed == [media_url("Sp1")]
