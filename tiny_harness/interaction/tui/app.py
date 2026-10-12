"""The TUI app (R20.2, R20.3, R20.4): the panes of ``design/tui-renderer.html`` on Textual.

Conversation on the left, Task / Plan / Trace tabs on the right, the composer below,
every action on a key. It is an A2A client: it sends messages and actions, streams the
reply, and keeps a ``SubscribeToTask`` stream per open task so a second surface sees
the same events.

issue-25 (``design/tui-task-controls.html``): the top bar shows ``STATE · sub-state``
(R5.7); ``ctrl+d`` completes and ``ctrl+c`` cancels the open task, both in the footer and
both disabled once it is terminal (R5.5); the composer completes ``/`` commands from the
card with a hint line of their descriptions (R6.7); the Task tab lists sub-tasks, Enter
opens one and ``f4`` returns to its parent (R9.4). The open tasks form a stack; each has
its own conversation, shown while it is on top.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import ClassVar, cast

import httpx
from a2a.types import Message, Task, TaskState, TaskStatusUpdateEvent
from a2a.utils.errors import A2AError
from google.protobuf import json_format, struct_pb2
from pydantic import ValidationError
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import (
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TabbedContent,
    TabPane,
)

from tiny_harness.harness.agents import A2AEvent
from tiny_harness.harness.channels import CHANNEL_EXT_MEDIA_TYPE
from tiny_harness.harness.commands import CommandSpec
from tiny_harness.harness.core import (
    STATUS_EXT_KEY,
    TERMINAL_STATES,
    HarnessTask,
    StatusExtensionData,
    StepState,
    TaskExtensionData,
    TaskRef,
)
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.interaction.a2ui import A2UI_MEDIA_TYPE, Action, parse_server_message
from tiny_harness.interaction.renderer import TEXT_PLAIN, Renderer, RenderItem, RenderPlan
from tiny_harness.interaction.tui.a2ui import Surfaces, SurfaceView
from tiny_harness.interaction.tui.client import A2AClientPort, SdkClient
from tiny_harness.jsontypes import JsonObject

CHEVRON = "\u203a"  # the prompt glyph of the prototype
COMMAND_MARK = "\u2318"  # marks a command's reply, as in the prototype
STEP_MARKS = {
    StepState.PENDING: "○",
    StepState.ACTIVE: "◐",
    StepState.DONE: "●",
    StepState.FAILED: "✗",
}
AWAITING_NEXT_MESSAGE = "awaiting-next-message"
# A SubscribeToTask stream follows a task until it ends (R5.6), but the stream of a
# message this surface sent ends at INPUT_REQUIRED: a task no subscription follows (the
# conversation started here, or one whose subscription ended) is re-read this often.
POLL_INTERVAL = 2.0
# What a refused or failed call raises: the server's A2A error, or the transport's.
CLIENT_ERRORS = (A2AError, httpx.HTTPError)


def short_id(task_id: str) -> str:
    return f"{task_id[:4]}…{task_id[-4:]}" if len(task_id) > 9 else task_id


def sub_state_of(metadata: struct_pb2.Struct) -> str | None:
    """The status extension's sub-state; ``None`` when absent or unknown, so an unknown
    value shows as plain ``INPUT_REQUIRED`` (R4.3)."""
    if STATUS_EXT_KEY not in metadata.fields:
        return None
    raw = cast(JsonObject, json_format.MessageToDict(metadata.fields[STATUS_EXT_KEY]))
    try:
        return StatusExtensionData.model_validate(raw).sub_state.value
    except ValidationError:
        return None


def event_task_id(event: A2AEvent) -> str:
    return event.id if isinstance(event, Task) else event.task_id


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
    """One conversation line; ``text`` keeps what it shows for tests and the trace. The
    text is never parsed as markup: it comes from the server and from the user."""

    def __init__(self, text: str, *, classes: str = "") -> None:
        super().__init__(text, classes=classes, markup=False)
        self.text = text

    DEFAULT_CSS = """
    Entry { height: auto; margin: 0 0 1 0; }
    Entry.you { color: $text; }
    Entry.agent { color: $accent; }
    Entry.status { color: $text-muted; }
    Entry.command { color: $text-muted; border-left: outer $accent; padding-left: 1; }
    Entry.help { color: $warning; }
    Entry.placeholder { color: $warning; }
    Entry.tool { color: $text-muted; }
    """


class SubTaskRow(ListItem):
    """A sub-task in the Task tab: ``id · state · goal``; Enter opens it (R9.4)."""

    def __init__(self, ref: TaskRef, text: str) -> None:
        self._label = Label(text, markup=False)
        super().__init__(self._label)
        self.ref = ref
        self.text = text

    def show(self, ref: TaskRef, text: str) -> None:
        self.ref = ref
        if text != self.text:
            self.text = text
            self._label.update(text)


@dataclass
class TaskView:
    """What the TUI knows about one task. Its conversation widgets carry ``css_class``
    and are displayed while the task is on top of the stack."""

    css_class: str
    state: int = TaskState.TASK_STATE_UNSPECIFIED
    sub_state: str | None = None
    ext: TaskExtensionData | None = None
    shown: str | None = None  # the last state line drawn, so a re-emitted state draws none
    seen: set[str] = field(default_factory=set[str])  # message ids already drawn

    @property
    def state_name(self) -> str:
        if self.state == TaskState.TASK_STATE_UNSPECIFIED:
            return "—"
        return TaskState.Name(cast(TaskState, self.state)).removeprefix("TASK_STATE_")

    @property
    def label(self) -> str:
        """``STATE · sub-state`` while ``INPUT_REQUIRED`` with a known sub-state (R5.7)."""
        if self.state == TaskState.TASK_STATE_INPUT_REQUIRED and self.sub_state:
            return f"{self.state_name} · {self.sub_state}"
        return self.state_name

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES


class HarnessApp(App[None]):
    """One surface over a stack of tasks. ``feed`` applies events without a client (tests,
    snapshots)."""

    TITLE = "tiny-harness"
    CSS = """
    #topbar { height: 1; background: $panel; color: $text; padding: 0 1; }
    #topbar-left { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    #topbar-right { width: auto; padding-left: 3; }
    #body { height: 1fr; }
    #conversation { width: 2fr; border: round $primary; padding: 0 1; }
    #side { width: 1fr; }
    .pane { padding: 0 1; height: auto; }
    #sub-tasks-title { padding: 0 1; color: $text-muted; }
    #sub-tasks { height: auto; max-height: 12; background: transparent; padding: 0 1; }
    SubTaskRow Label { width: 1fr; }
    #hint { height: 1; padding: 0 1; color: $text-muted; }
    """
    # The controls refuse on a terminal task (or none): the shown binding is then disabled
    # (dimmed in the footer) and the hidden one shows why instead.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "focus_next", "pane"),
        Binding("f2", "cycle_pane", "task/plan/trace"),
        Binding("ctrl+d", "complete_task", "complete", priority=True),
        Binding("ctrl+c", "cancel_task", "cancel", priority=True),
        Binding("ctrl+d,ctrl+c", "closed_notice", show=False, priority=True),
        Binding("f4", "parent_task", "parent"),
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
        poll_interval: float | None = POLL_INTERVAL,
    ) -> None:
        super().__init__()
        self.client = client
        self.poll_interval = poll_interval
        self.url = url
        self.agent = agent
        self.version = version
        self.participant = participant
        self.context_id = context_id
        self.stack: list[str] = [task_id] if task_id else []
        self.views: dict[str, TaskView] = {}
        self.commands: tuple[CommandSpec, ...] = client.commands() if client else ()
        self.renderer = TuiRenderer()
        self.surfaces = Surfaces()
        self.trace: list[str] = []
        self.help_pending = False
        self._rows: list[SubTaskRow] = []
        self._subscribed: set[str] = set()
        self._following: set[str] = set()  # tasks a live subscription follows

    # --- the task stack ---------------------------------------------------------------

    @property
    def task_id(self) -> str | None:
        """The open task: the top of the stack."""
        return self.stack[-1] if self.stack else None

    @task_id.setter
    def task_id(self, value: str) -> None:
        old = self.task_id or ""
        if self.stack:
            self.stack[-1] = value
        else:
            self.stack.append(value)
        if old in self.views and value not in self.views:
            self.views[value] = self.views.pop(old)

    @property
    def view(self) -> TaskView | None:
        return self.views.get(self.task_id or "")

    @property
    def state_name(self) -> str:
        return self.view.state_name if self.view else "—"

    @property
    def sub_state(self) -> str | None:
        return self.view.sub_state if self.view else None

    @property
    def ext(self) -> TaskExtensionData | None:
        return self.view.ext if self.view else None

    def _new_view(self, key: str) -> TaskView:
        view = TaskView(css_class=f"view-{len(self.views)}")
        self.views[key] = view
        return view

    def _view_for(self, task_id: str) -> TaskView:
        """The view an event of ``task_id`` belongs to. The first task this surface sees
        takes over the view the composer has been writing to."""
        current = self.view
        if not task_id and current is not None:
            return current
        if task_id in self.views:
            return self.views[task_id]
        if not self.stack and "" in self.views:
            self.task_id = task_id
            return self.views[task_id]
        return self._new_view(task_id)

    # --- layout ------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        self._new_view(self.task_id or "")
        left, right = self._topbar_parts()
        with Horizontal(id="topbar"):
            yield Static(left, id="topbar-left", markup=False)
            yield Static(right, id="topbar-right", markup=False)
        with Horizontal(id="body"):
            yield VerticalScroll(id="conversation")
            with TabbedContent(id="side"):
                with TabPane("Task", id="task"):
                    yield Static("(no task yet)", id="task-pane", classes="pane", markup=False)
                    yield Static("", id="sub-tasks-title", markup=False)
                    yield ListView(id="sub-tasks")
                with TabPane("Plan", id="plan"):
                    yield Static("(no plan yet)", id="plan-pane", classes="pane", markup=False)
                with TabPane("Trace", id="trace"):
                    yield Static("(no events yet)", id="trace-pane", classes="pane", markup=False)
        placeholder = f"Enter to send as {self.participant}"
        if self.commands:
            placeholder += " · / for commands"
        yield Input(
            placeholder=placeholder,
            id="composer",
            suggester=SuggestFromList([f"/{c.name}" for c in self.commands], case_sensitive=True),
        )
        yield Static("", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#composer", Input).focus()
        self.query_one("#sub-tasks-title", Static).display = False
        if self.task_id:
            self._subscribe_once(self.task_id)
        if self.client is not None and self.poll_interval:
            self.set_interval(self.poll_interval, self._poll_open_tasks)

    def _topbar_parts(self) -> tuple[str, str]:
        """The harness on the left; on the right, the open task (after its parents) and
        ``STATE · sub-state``, which an ellipsis on the left never hides (R5.7)."""
        if self.task_id:
            crumb = "".join(f"{short_id(t)} {CHEVRON} " for t in self.stack[:-1])
            task = f"{crumb}task {short_id(self.task_id)}"
        else:
            task = "no task"
        state = self.view.label if self.view else "—"
        harness = f"tiny-harness · {self.agent} v{self.version} · A2A 1.0 · {self.url}"
        return harness, f"{task} · {state}"

    def topbar_text(self) -> str:
        return "   ".join(self._topbar_parts())

    # --- events in --------------------------------------------------------------------

    def feed(self, events: Iterable[A2AEvent]) -> None:
        for event in events:
            self.apply_event(event)

    def apply_event(self, event: A2AEvent) -> None:
        view = self._view_for(event_task_id(event))
        message: Message | None = None
        if isinstance(event, Message):
            message = event
        elif isinstance(event, Task | TaskStatusUpdateEvent):
            if isinstance(event, Task):
                self._set_ext(view, event)
            if event.status.state != TaskState.TASK_STATE_UNSPECIFIED:
                view.state, view.sub_state = event.status.state, sub_state_of(event.metadata)
            if event.status.HasField("message"):
                message = event.status.message
        plan = self.renderer.plan(event)
        self.renderer.render(plan)
        items = list(plan.items)
        if message is not None and message.message_id:
            # A Task snapshot repeats the status message a stream already showed.
            if message.message_id in view.seen:
                items = [i for i in items if i.kind == "status"]
            view.seen.add(message.message_id)
        command = message is not None and "command" in message.metadata.fields
        # The message first, then the state it left the task in ("… · your turn").
        items.sort(key=lambda i: i.kind == "status")
        for item in items:
            self._draw(item, view, command=command)
        self._refresh_panes()

    def _set_ext(self, view: TaskView, task: Task) -> None:
        """A task without the extension (a bare ``CancelTask`` reply) keeps what the view
        knew."""
        try:
            view.ext = HarnessTask(task).ext
        except ValueError:
            return

    def _mount(self, view: TaskView, widget: Widget) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        widget.add_class(view.css_class)
        widget.display = view is self.view
        conversation.mount(widget)
        conversation.scroll_end(animate=False)

    def _notice(self, text: str, view: TaskView | None = None) -> None:
        target = view or self.view
        if target is not None:
            self._mount(target, Entry(text, classes="status"))

    def _draw(self, item: RenderItem, view: TaskView, *, command: bool = False) -> None:
        if item.kind == "text" and command:
            self._mount(view, Entry(f"{COMMAND_MARK} {item.text}", classes="command"))
            self.trace.append("command reply")
        elif item.kind == "text":
            who = f"you {CHEVRON}" if item.role == "user" else f"agent {CHEVRON}"
            self._mount(view, Entry(f"{who} {item.text}", classes=item.role))
            self.trace.append(f"message · {item.role}")
        elif item.kind == "status":
            if view.state == TaskState.TASK_STATE_UNSPECIFIED:
                return
            if view.label != view.shown:
                turn = " · your turn" if view.sub_state == AWAITING_NEXT_MESSAGE else ""
                self._mount(view, Entry(f"── task → {view.label}{turn}", classes="status"))
                self.trace.append(f"status · {view.label}")
            view.shown = view.label
            if view.state == TaskState.TASK_STATE_INPUT_REQUIRED:
                self.help_pending = True
        elif item.kind == "data" and item.media_type == A2UI_MEDIA_TYPE and item.data is not None:
            self._draw_a2ui(item.data, view)
        elif item.kind == "data" and item.media_type == CHANNEL_EXT_MEDIA_TYPE and item.data:
            kind = str(item.data.get("kind", "message"))
            text = str(item.data.get("text", ""))
            if kind == "help_request":
                self._mount(view, Entry(f"? help requested {CHEVRON} {text}", classes="help"))
                self.trace.append("help requested")
            else:
                sender = item.data.get("sender", "?")
                self._mount(view, Entry(f"{sender} {CHEVRON} {text}", classes="agent"))
        else:
            self._mount(view, Entry(item.text, classes="placeholder"))
            self.trace.append(f"placeholder · {item.media_type}")

    def _draw_a2ui(self, payload: JsonObject, view: TaskView) -> None:
        conversation = self.query_one("#conversation", VerticalScroll)
        message = parse_server_message(payload)
        surface = self.surfaces.apply(message)
        if surface is None or message.kind != "updateComponents":
            return
        for existing in conversation.query(SurfaceView):
            if existing.surface.surface_id == surface.surface_id:
                existing.remove()
        self._mount(view, SurfaceView(surface, on_action=self.send_action))
        self.trace.append(f"a2ui · surface {surface.surface_id}")

    def _refresh_panes(self) -> None:
        left, right = self._topbar_parts()
        self.query_one("#topbar-left", Static).update(left)
        self.query_one("#topbar-right", Static).update(right)
        self.query_one("#task-pane", Static).update(self._task_text())
        self.query_one("#plan-pane", Static).update(self._plan_text())
        self.query_one("#trace-pane", Static).update(
            "\n".join(self.trace[-20:]) or "(no events yet)"
        )
        self._sync_sub_tasks()
        self.refresh_bindings()

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
        lines.append("")
        lines.append("Settings")
        lines.append(f"  model  {ext.model or 'configured default'}")
        lines.append(f"  effort {ext.reasoning_effort or 'provider default'}")
        return "\n".join(lines)

    def _row_text(self, ref: TaskRef) -> str:
        if ref.agent is not None:  # on another agent: this surface cannot see it
            return f"{ref.agent.id}/{ref.task_id} · — · —"
        view = self.views.get(ref.task_id)
        state = view.state_name if view else "—"
        goal = view.ext.goal if view and view.ext else "—"
        return f"{short_id(ref.task_id)} · {state} · {goal}"

    def _sync_sub_tasks(self) -> None:
        """One row per sub-task of the open task. The TUI follows each local one, so its
        row shows the state and goal and stays current (R5.6)."""
        refs = self.ext.sub_tasks if self.ext else ()
        title = self.query_one("#sub-tasks-title", Static)
        title.display = self.ext is not None
        title.update("Sub-tasks · Enter opens" if refs else "Sub-tasks\n  none")
        listing = self.query_one("#sub-tasks", ListView)
        for index, ref in enumerate(refs):
            text = self._row_text(ref)
            if index < len(self._rows):
                self._rows[index].show(ref, text)
            else:
                row = SubTaskRow(ref, text)
                self._rows.append(row)
                listing.append(row)
        for row in self._rows[len(refs) :]:
            row.remove()
        del self._rows[len(refs) :]
        if refs and listing.index is None:
            self.call_after_refresh(self._highlight_first_row)
        for ref in refs:
            if ref.agent is None:
                self._subscribe_once(ref.task_id)

    def _highlight_first_row(self) -> None:
        """Enter selects the highlighted row; rows appended to an empty list have none."""
        listing = self.query_one("#sub-tasks", ListView)
        if listing.index is None and self._rows:
            listing.index = 0

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

    def _show_open_task(self) -> None:
        view = self.view
        conversation = self.query_one("#conversation", VerticalScroll)
        for child in conversation.children:
            child.display = view is not None and child.has_class(view.css_class)
        conversation.scroll_end(animate=False)
        self._refresh_panes()

    # --- events out -------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "composer":
            self.query_one("#hint", Static).update(self._hint(event.value))

    def _hint(self, value: str) -> Text:
        """The commands matching a ``/`` prefix, with their argument hint and description
        (R6.7); nothing once the name is complete (a space follows) or for plain text."""
        if not value.startswith("/") or " " in value:
            return Text()
        prefix = value[1:]
        hint = Text()
        for spec in (c for c in self.commands if c.name.startswith(prefix)):
            if hint:
                hint.append("   ")
            hint.append(f"/{spec.name}", style="bold")
            if spec.argument_hint:
                hint.append(f" {spec.argument_hint}")
            hint.append(f" — {spec.description}")
        return hint

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        view = self.view
        if view is not None and view.terminal:
            self._notice(f"── task is {view.state_name}; nothing sent")
            return
        if view is not None:
            self._mount(view, Entry(f"you {CHEVRON} {text}", classes="you"))
        if self.client is not None:
            self.run_worker(self._send(text), exclusive=False)

    async def _send(self, text: str) -> None:
        assert self.client is not None
        try:
            async for event in self.client.send(
                text, task_id=self.task_id, context_id=self.context_id
            ):
                self.apply_event(event)
        except CLIENT_ERRORS as exc:
            self._notice(f"── {exc}")

    def _subscribe_once(self, task_id: str) -> None:
        if self.client is not None and task_id not in self._subscribed:
            self._subscribed.add(task_id)
            self.run_worker(self._subscribe(task_id), exclusive=False)

    async def _subscribe(self, task_id: str) -> None:
        assert self.client is not None
        self._following.add(task_id)
        try:
            async for event in self.client.subscribe(task_id):
                self.apply_event(event)
        except CLIENT_ERRORS as exc:  # e.g. the task is already terminal: one snapshot
            self.trace.append(f"subscription {short_id(task_id)} ended: {exc}")
            await self._fetch(task_id)
        finally:
            self._following.discard(task_id)  # the poll takes over while it is open

    async def _fetch(self, task_id: str) -> None:
        assert self.client is not None
        try:
            task = await self.client.get_task(task_id)
        except CLIENT_ERRORS as exc:
            self.trace.append(f"task {short_id(task_id)} unavailable: {exc}")
            return
        self.apply_event(task)

    def _poll_open_tasks(self) -> None:
        """Re-read every non-terminal task on the stack and the open task's local
        sub-tasks that no live subscription follows. Applying an unchanged task draws
        nothing: states and messages already shown are not drawn again."""
        ids = [t for t in self.stack if not (t in self.views and self.views[t].terminal)]
        for ref in self.ext.sub_tasks if self.ext else ():
            view = self.views.get(ref.task_id)
            if ref.agent is None and not (view and view.terminal) and ref.task_id not in ids:
                ids.append(ref.task_id)
        ids = [t for t in ids if t not in self._following]
        if ids:
            self.run_worker(self._poll(ids), exclusive=True, group="poll")

    async def _poll(self, task_ids: list[str]) -> None:
        assert self.client is not None
        for task_id in task_ids:
            try:
                task = await self.client.get_task(task_id)
            except CLIENT_ERRORS:
                continue  # the next poll tries again
            self.apply_event(task)

    def send_action(self, action: Action) -> None:
        if self.view is not None:
            text = f"you {CHEVRON} {action.name} {json.dumps(action.context)}"
            self._mount(self.view, Entry(text, classes="you"))
        if self.client is not None and self.task_id:
            self.run_worker(self._send_action(action), exclusive=False)

    async def _send_action(self, action: Action) -> None:
        assert self.client is not None and self.task_id is not None
        try:
            async for event in self.client.send_action(
                action, task_id=self.task_id, context_id=self.context_id
            ):
                self.apply_event(event)
        except CLIENT_ERRORS as exc:
            self._notice(f"── {exc}")

    # --- key bindings ------------------------------------------------------------------

    def _controllable(self) -> bool:
        return self.task_id is not None and not (self.view is not None and self.view.terminal)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """``None`` shows a binding disabled; ``False`` hides it (Textual's contract)."""
        if action in ("complete_task", "cancel_task"):
            return True if self._controllable() else None
        if action == "closed_notice":
            return not self._controllable()
        if action == "parent_task":
            return True if len(self.stack) > 1 else None
        return True

    def action_cycle_pane(self) -> None:
        side = self.query_one("#side", TabbedContent)
        order = ["task", "plan", "trace"]
        current = side.active or "task"
        side.active = order[(order.index(current) + 1) % len(order)] if current in order else "task"

    def action_closed_notice(self) -> None:
        self._notice(f"── already {self.state_name}" if self.task_id else "── no task open")

    def action_complete_task(self) -> None:
        if self.client is not None and self.task_id:
            self.run_worker(self._complete(self.task_id), exclusive=False)

    async def _complete(self, task_id: str) -> None:
        """The control envelope through ``SendMessage``, as any A2A client sends it (R5.1);
        the final ``COMPLETED`` update, or the refusal, streams back."""
        assert self.client is not None
        try:
            async for event in self.client.complete(task_id):
                self.apply_event(event)
        except CLIENT_ERRORS as exc:
            self._notice(f"── {exc}", self.views.get(task_id))

    async def action_cancel_task(self) -> None:
        if self.client is None or not self.task_id:
            return
        try:
            task = await self.client.cancel(self.task_id)
        except CLIENT_ERRORS as exc:
            self._notice(f"── {exc}")
            return
        self.apply_event(task)

    def action_parent_task(self) -> None:
        if len(self.stack) > 1:
            self.stack.pop()
            self._show_open_task()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, SubTaskRow):
            self.open_sub_task(event.item.ref)

    def open_sub_task(self, ref: TaskRef) -> None:
        """Push a local sub-task and follow it; a remote one lives on its own agent."""
        if ref.agent is not None:
            self._notice(f"── sub-task {ref.task_id} is on {ref.agent.id}; open it there")
            return
        if ref.task_id not in self.views:
            self._new_view(ref.task_id)
        self.stack.append(ref.task_id)
        self._show_open_task()
        self._subscribe_once(ref.task_id)


async def run_tui(url: str, *, participant: str) -> int:
    client = await SdkClient.connect(url, participant=participant)
    try:
        await HarnessApp(client, url=url, participant=participant).run_async()
    finally:
        await client.close()
    return 0


__all__ = [
    "CHEVRON",
    "STEP_MARKS",
    "Entry",
    "HarnessApp",
    "SubTaskRow",
    "TaskView",
    "TuiRenderer",
    "run_tui",
]
