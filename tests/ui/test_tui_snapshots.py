"""T5/T6: the TUI's states match the accepted snapshots (``--snapshot-update`` to accept)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import PurePath
from typing import Any, Protocol

from textual.app import App
from textual.pilot import Pilot
from textual.widgets import ListView

from tests.ui.prototype import (
    COMMANDS,
    TASK_ID,
    completed_events,
    conversation_events,
    prototype_events,
    sub_task,
    sub_task_events,
)
from tiny_harness.interaction.tui import HarnessApp, ScriptedClient


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
