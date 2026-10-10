"""The TUI app (R20.2, R20.3, R20.4): the panes of ``design/tui-renderer.html`` on Textual.

Conversation on the left, Task / Plan / Trace tabs on the right, the composer below,
every action on a key. It is an A2A client: it sends messages and actions, streams the
reply, and keeps a ``SubscribeToTask`` stream per open task so a second surface sees
the same events.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import ClassVar

from a2a.types import Task, TaskArtifactUpdateEvent, TaskStatusUpdateEvent
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Input, Static, TabbedContent, TabPane

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.channels import CHANNEL_EXT_MEDIA_TYPE
from tiny_harness.harness.core import HarnessTask, StepState, TaskExtensionData
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.interaction.a2ui import A2UI_MEDIA_TYPE, Action, parse_server_message
from tiny_harness.interaction.renderer import TEXT_PLAIN, Renderer, RenderItem, RenderPlan
from tiny_harness.interaction.tui.a2ui import Surfaces, SurfaceView
from tiny_harness.interaction.tui.client import A2AClientPort, SdkClient
from tiny_harness.jsontypes import JsonObject

CHEVRON = "\u203a"  # the prompt glyph of the prototype
STEP_MARKS = {
    StepState.PENDING: "○",
    StepState.ACTIVE: "◐",
    StepState.DONE: "●",
    StepState.FAILED: "✗",
}


class TuiRenderer(Renderer):
    """What the TUI draws: text, A2UI parts and channel parts; the rest is a placeholder."""

    def __init__(self) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.RENDERER, id="tui", version=None),
            supported=(TEXT_PLAIN, A2UI_MEDIA_TYPE, CHANNEL_EXT_MEDIA_TYPE),
        )
        self.plans: list[RenderPlan] = []

    def render(self, plan: RenderPlan) -> None:
        self.plans.append(plan)


class Entry(Static):
    """One conversation line; ``text`` keeps what it shows for tests and the trace."""

    def __init__(self, text: str, *, classes: str = "") -> None:
        super().__init__(text, classes=classes)
        self.text = text

    DEFAULT_CSS = """
    Entry { height: auto; margin: 0 0 1 0; }
    Entry.you { color: $text; }
    Entry.agent { color: $accent; }
    Entry.status { color: $text-muted; }
    Entry.help { color: $warning; }
    Entry.placeholder { color: $warning; }
    Entry.tool { color: $text-muted; }
    """


class HarnessApp(App[None]):
    """One task's surface. ``feed`` applies events without a client (tests, snapshots)."""

    TITLE = "tiny-harness"
    CSS = """
    #topbar { height: 1; background: $panel; color: $text; padding: 0 1; }
    #body { height: 1fr; }
    #conversation { width: 2fr; border: round $primary; padding: 0 1; }
    #side { width: 1fr; }
    #composer { dock: bottom; }
    .pane { padding: 0 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "focus_next", "pane"),
        Binding("f2", "cycle_pane", "task/plan/trace"),
        Binding("ctrl+c", "cancel_task", "cancel task", priority=True),
        Binding("q", "quit", "quit"),
    ]

    def __init__(
        self,
        client: A2AClientPort | None = None,
        *,
        url: str = "http://localhost:8080",
        agent: str = "support-agent",
        version: str = "0.1.0",
        participant: str = "you",
        context_id: str = "ctx-tui",
        task_id: str | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.url = url
        self.agent = agent
        self.version = version
        self.participant = participant
        self.context_id = context_id
        self.task_id = task_id
        self.state_name = "—"
        self.renderer = TuiRenderer()
        self.surfaces = Surfaces()
        self.ext: TaskExtensionData | None = None
        self.trace: list[str] = []
        self.help_pending = False

    # --- layout ------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self.topbar_text(), id="topbar")
        with Horizontal(id="body"):
            yield VerticalScroll(id="conversation")
            with TabbedContent(id="side"):
                with TabPane("Task", id="task"):
                    yield Static("(no task yet)", id="task-pane", classes="pane")
                with TabPane("Plan", id="plan"):
                    yield Static("(no plan yet)", id="plan-pane", classes="pane")
                with TabPane("Trace", id="trace"):
                    yield Static("(no events yet)", id="trace-pane", classes="pane")
        yield Input(placeholder=f"Enter to send as {self.participant}", id="composer")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#composer", Input).focus()
        if self.task_id and self.client is not None:
            self.run_worker(self._subscribe(self.task_id), exclusive=False)

    def topbar_text(self) -> str:
        task = f"task {self.task_id[:4]}…{self.task_id[-4:]}" if self.task_id else "no task"
        return (
            f"tiny-harness · {self.agent} v{self.version} · A2A 1.0 · {self.url}   "
            f"{task} · {self.state_name}"
        )

    # --- events in --------------------------------------------------------------------

    def feed(self, events: Iterable[A2AEvent]) -> None:
        for event in events:
            self.apply_event(event)

    def apply_event(self, event: A2AEvent) -> None:
        if isinstance(event, Task):
            self.task_id = event.id
            self._set_ext(event)
        elif isinstance(event, TaskStatusUpdateEvent | TaskArtifactUpdateEvent):
            self.task_id = event.task_id or self.task_id
        plan = self.renderer.plan(event)
        self.renderer.render(plan)
        for item in plan.items:
            self._draw(item)
        self._refresh_panes()

    def _set_ext(self, task: Task) -> None:
        try:
            self.ext = HarnessTask(task).ext
        except ValueError:
            self.ext = None

    def _draw(self, item: RenderItem) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        if item.kind == "text":
            who = f"you {CHEVRON}" if item.role == "user" else f"agent {CHEVRON}"
            conversation.mount(Entry(f"{who} {item.text}", classes=item.role))
            self.trace.append(f"message · {item.role}")
        elif item.kind == "status":
            if item.text != self.state_name or not self.trace:
                conversation.mount(Entry(f"── task → {item.text}", classes="status"))
                self.trace.append(f"status · {item.text}")
            self.state_name = item.text
            if item.text == "INPUT_REQUIRED":
                self.help_pending = True
        elif item.kind == "data" and item.media_type == A2UI_MEDIA_TYPE and item.data is not None:
            self._draw_a2ui(item.data)
        elif item.kind == "data" and item.media_type == CHANNEL_EXT_MEDIA_TYPE and item.data:
            kind = str(item.data.get("kind", "message"))
            text = str(item.data.get("text", ""))
            if kind == "help_request":
                conversation.mount(Entry(f"? help requested {CHEVRON} {text}", classes="help"))
                self.trace.append("help requested")
            else:
                conversation.mount(
                    Entry(f"{item.data.get('sender', '?')} {CHEVRON} {text}", classes="agent")
                )
        else:
            conversation.mount(Entry(item.text, classes="placeholder"))
            self.trace.append(f"placeholder · {item.media_type}")
        conversation.scroll_end(animate=False)

    def _draw_a2ui(self, payload: JsonObject) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        message = parse_server_message(payload)
        surface = self.surfaces.apply(message)
        if surface is None or message.kind != "updateComponents":
            return
        for existing in conversation.query(SurfaceView):
            if existing.surface.surface_id == surface.surface_id:
                existing.remove()
        conversation.mount(SurfaceView(surface, on_action=self.send_action))
        self.trace.append(f"a2ui · surface {surface.surface_id}")

    def _refresh_panes(self) -> None:
        self.query_one("#topbar", Static).update(self.topbar_text())
        self.query_one("#task-pane", Static).update(self._task_text())
        self.query_one("#plan-pane", Static).update(self._plan_text())
        self.query_one("#trace-pane", Static).update(
            "\n".join(self.trace[-20:]) or "(no events yet)"
        )

    def _task_text(self) -> str:
        ext = self.ext
        if ext is None:
            return "(no task yet)"
        lines = ["Goal", f"  {ext.goal}", ""]
        if ext.acceptance_criteria:
            lines.append("Acceptance criteria")
            lines.extend(f"  [{'x' if c.met else ' '}] {c.text}" for c in ext.acceptance_criteria)
            lines.append("")
        lines.append("Participants")
        lines.extend(f"  {p.id}  {p.role.value}" for p in ext.participants)
        if ext.sub_tasks:
            lines.append("")
            lines.append("Sub-tasks")
            lines.extend(
                f"  {t.agent.id + '/' if t.agent else ''}{t.task_id}" for t in ext.sub_tasks
            )
        return "\n".join(lines)

    def _plan_text(self) -> str:
        if self.ext is None or self.ext.plan is None:
            return "(no plan yet)"
        lines = [f"Plan · {len(self.ext.plan.steps)} steps"]
        for index, step in enumerate(self.ext.plan.steps, start=1):
            lines.append(f"  {STEP_MARKS[step.state]} {index} {step.name}")
            if step.output:
                lines.append(f"      → {step.output}")
            elif step.depends_on:
                lines.append(f"      depends on {', '.join(step.depends_on)}")
        return "\n".join(lines)

    # --- events out -------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.query_one("#conversation", VerticalScroll).mount(
            Entry(f"you {CHEVRON} {text}", classes="you")
        )
        if self.client is not None:
            self.run_worker(self._send(text), exclusive=False)

    async def _send(self, text: str) -> None:
        assert self.client is not None
        async for event in self.client.send(text, task_id=self.task_id, context_id=self.context_id):
            self.apply_event(event)

    async def _subscribe(self, task_id: str) -> None:
        assert self.client is not None
        async for event in self.client.subscribe(task_id):
            self.apply_event(event)

    def send_action(self, action: Action) -> None:
        self.query_one("#conversation", VerticalScroll).mount(
            Entry(f"you {CHEVRON} {action.name} {json.dumps(action.context)}", classes="you")
        )
        if self.client is not None and self.task_id:
            self.run_worker(self._send_action(action), exclusive=False)

    async def _send_action(self, action: Action) -> None:
        assert self.client is not None and self.task_id is not None
        async for event in self.client.send_action(
            action, task_id=self.task_id, context_id=self.context_id
        ):
            self.apply_event(event)

    # --- key bindings ------------------------------------------------------------------

    def action_cycle_pane(self) -> None:
        side = self.query_one("#side", TabbedContent)
        order = ["task", "plan", "trace"]
        current = side.active or "task"
        side.active = order[(order.index(current) + 1) % len(order)] if current in order else "task"

    async def action_cancel_task(self) -> None:
        if self.client is None or not self.task_id:
            return
        task = await self.client.cancel(self.task_id)
        self.apply_event(task)


async def run_tui(url: str, *, participant: str) -> int:
    client = await SdkClient.connect(url, participant=participant)
    try:
        await HarnessApp(client, url=url, participant=participant).run_async()
    finally:
        await client.close()
    return 0


__all__ = ["CHEVRON", "STEP_MARKS", "Entry", "HarnessApp", "TuiRenderer", "run_tui"]
