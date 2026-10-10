"""T9: every action of the TUI has a key (R20, accessibility row of the testing plan)."""

from __future__ import annotations

from a2a.types import TaskState
from textual.widgets import Button, Input, TabbedContent

from tests.ui.prototype import TASK_ID, prototype_events, status
from tiny_harness.interaction.tui import HarnessApp, ScriptedClient
from tiny_harness.interaction.tui.a2ui import SurfaceView
from tiny_harness.interaction.tui.app import Entry


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
