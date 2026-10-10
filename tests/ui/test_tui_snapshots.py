"""T5/T6: the TUI's states match the accepted snapshots (``--snapshot-update`` to accept)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import PurePath
from typing import Any, Protocol

from textual.app import App
from textual.pilot import Pilot

from tests.ui.prototype import TASK_ID, prototype_events
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
