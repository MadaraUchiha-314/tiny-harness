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

issue-38 (``design/tui-multimodal.html``): ``/attach <path>`` runs here because the card
lists it as a surface command; it checks the file against the card's media params and
adds a chip above the composer (``Backspace`` on an empty composer removes the last).
A message goes out with its files as ``raw`` parts; the server's echo of it gives each
file its media URL. Images draw inline or as the line naming where they were saved;
audio and recordings are entries that play on ``Enter`` and show their transcript.
Where the card accepts WAV audio, holding Space on an empty composer (or ``F5``) records a
voice turn, with the recording bar above the composer; ``F6`` asks for spoken replies
(``speak``), which play as they stream with a speaking line; ``Escape`` stops them, and
Enter on the line replays. Textual reports no key-release events, so a hold ends when the
terminal's auto-repeat stops (``--hold-ms`` adjusts the repeat window).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, cast

import httpx
from a2a.types import (
    Message,
    Part,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.utils.errors import A2AError
from google.protobuf import json_format, struct_pb2
from pydantic import ValidationError
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
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
from tiny_harness.harness.commands import CommandSpec, parse_command_text
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
from tiny_harness.harness.media import ACCEPTED, PCM_MEDIA_TYPE
from tiny_harness.harness.media.extension import MEDIA_ROUTE, MediaPartMetadata
from tiny_harness.interaction.a2ui import A2UI_MEDIA_TYPE, Action, parse_server_message
from tiny_harness.interaction.renderer import (
    TEXT_PLAIN,
    Renderer,
    RenderItem,
    RenderPlan,
    is_media_part,
)
from tiny_harness.interaction.tui.a2ui import Surfaces, SurfaceView
from tiny_harness.interaction.tui.client import A2AClientPort, Attachment, SdkClient, user_parts
from tiny_harness.interaction.tui.composer import Composer, ComposerSuggester
from tiny_harness.interaction.tui.media import (
    AttachRefused,
    AudioEntry,
    ImageView,
    MediaCache,
    MediaCacheError,
    MediaEntry,
    SpeechEntry,
    chip_text,
    clock,
    graphics_image_view,
    human_size,
    load_attachment,
    media_ids,
    rejection_text,
)
from tiny_harness.interaction.tui.voice import (
    SPEECH_FORMAT,
    HoldDetector,
    PcmPlayer,
    Recorder,
    VoiceUnavailable,
    meter,
    once,
    wav_pcm,
)
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
# A subscription that drops while its task is open is opened again after this long.
RESUBSCRIBE_DELAY = 2.0
# What a refused or failed call raises: the server's A2A error, or the transport's.
CLIENT_ERRORS = (A2AError, httpx.HTTPError)
MESSAGE_ARTIFACT = "message:"  # the user's message as stored, with its media URLs
TRANSCRIPT_ARTIFACT = "transcript:"
# A fetched medium larger than this is not cached (the card's per-file limit wins).
MAX_FETCH_BYTES = 64 * 1024 * 1024
VOICE_TICK = 0.05  # the hold detector's and the meters' timer, in seconds
RECORDING_TYPE = "audio/wav"


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
            supported=(
                TEXT_PLAIN,
                A2UI_MEDIA_TYPE,
                CHANNEL_EXT_MEDIA_TYPE,
                *ACCEPTED,
                PCM_MEDIA_TYPE,
            ),
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
    Entry.error { color: $error; }
    """


class Turn(Vertical):
    """One message of the conversation drawn on several lines (its files, then its text),
    with no gap between them (issue-38)."""

    DEFAULT_CSS = """
    Turn { height: auto; margin: 0 0 1 0; }
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
    # The newest status applied, and every one applied: a SubscribeToTask stream replays
    # the task's log from the start, and what this surface already showed stays put.
    at: tuple[int, int] = (0, 0)
    applied: set[tuple[int, int, int]] = field(default_factory=set[tuple[int, int, int]])
    # issue-38: this surface's messages with files, oldest first, until the server's echo
    # gives their files media URLs; audio entries by media id, for their transcripts.
    pending: list[list[Widget]] = field(default_factory=list[list[Widget]])
    audio: dict[str, AudioEntry] = field(default_factory=dict[str, AudioEntry])
    transcripts: dict[str, str] = field(default_factory=dict[str, str])
    # A spoken reply's line arrives before the reply's text; it moves below that text.
    unplaced: SpeechEntry | None = None

    def replayed(self, status: TaskStatus) -> bool:
        """``status`` is one this view already applied, or older than the newest; a
        status without a timestamp (a bare ``CancelTask`` reply) always applies."""
        if not status.HasField("timestamp"):
            return False
        stamp = (status.timestamp.seconds, status.timestamp.nanos)
        key = (*stamp, int(status.state))
        if key in self.applied or stamp < self.at:
            return True
        self.applied.add(key)
        self.at = stamp
        return False

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
    #chips { height: auto; padding: 0 1; color: $text-muted; }
    #rec { height: 1; padding: 0 1; color: $error; }
    Turn > Entry, Turn > AudioEntry, Turn > MediaEntry { margin: 0; }
    """
    # The controls refuse on a terminal task (or none): the shown binding is then disabled
    # (dimmed in the footer) and the hidden one shows why instead.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("f5", "toggle_record", "talk"),
        Binding("f6", "toggle_speak", "spoken replies"),
        Binding("escape", "stop_voice", "stop"),
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
        resubscribe_delay: float = RESUBSCRIBE_DELAY,
        media_cache: MediaCache | None = None,
        image_view: ImageView | None = None,
        recorder: Recorder | None = None,
        player: PcmPlayer | None = None,
        hold: HoldDetector | None = None,
        hold_ms: int | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.resubscribe_delay = resubscribe_delay
        self.url = url
        self.agent = agent
        self.version = version
        self.participant = participant
        self.context_id = context_id
        self.stack: list[str] = [task_id] if task_id else []
        self.views: dict[str, TaskView] = {}
        self.commands: tuple[CommandSpec, ...] = client.commands() if client else ()
        self.media_params = client.media() if client else None
        self.media_cache = media_cache or MediaCache()
        self.image_view = image_view
        self.attachments: list[Attachment] = []
        # Voice (issue-38 R3, R4): devices are opened only when used, so a TUI without
        # PortAudio starts and types as before.
        self.recorder = recorder or Recorder()
        self.player = player or PcmPlayer()
        window = hold_ms / 1000 if hold_ms else 0.6
        self.hold = hold or HoldDetector(repeat_window=window)
        self.recording: str | None = None  # "hold" or "toggle" while the microphone is open
        self.speak_replies = False
        self.speaking: SpeechEntry | None = None
        # Surface commands this client implements; it runs one only when the card lists it
        # as a surface command (the commands come from the registry, issue-38 R1.2).
        implemented: dict[str, Callable[[str], None]] = {"attach": self._attach_file}
        self.local_commands = {
            c.name: implemented[c.name]
            for c in self.commands
            if c.runs_on == "surface" and c.name in implemented
        }
        self.renderer = TuiRenderer()
        self.surfaces = Surfaces()
        self.trace: list[str] = []
        self.help_pending = False
        self._rows: list[SubTaskRow] = []
        self._subscribed: set[str] = set()
        self._read: set[str] = set()  # sub-tasks read once for their row's goal

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
        yield Static("", id="chips")
        yield Static("", id="rec", markup=False)
        yield Composer(
            placeholder=placeholder,
            id="composer",
            suggester=ComposerSuggester(
                [c.name for c in self.commands], path_commands=list(self.local_commands)
            ),
        )
        yield Static("", id="hint")
        yield Footer()

    def on_mount(self) -> None:
        composer = self.query_one("#composer", Composer)
        composer.focus()
        composer.hold_space = self.voice_input
        self.query_one("#sub-tasks-title", Static).display = False
        self.query_one("#rec", Static).display = False
        self._show_chips()
        if self.voice_input or self.voice_output:
            self.set_interval(VOICE_TICK, self._voice_tick)
        if self.task_id:
            self._subscribe_once(self.task_id)

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
        right = f"{task} · {state}"
        if self.voice_output:
            right += f"   🔈 spoken replies: {'on' if self.speak_replies else 'off'} (F6)"
        return harness, right

    def topbar_text(self) -> str:
        return "   ".join(self._topbar_parts())

    # --- events in --------------------------------------------------------------------

    def feed(self, events: Iterable[A2AEvent]) -> None:
        for event in events:
            self.apply_event(event)

    def apply_event(self, event: A2AEvent) -> None:
        view = self._view_for(event_task_id(event))
        if isinstance(event, TaskArtifactUpdateEvent) and self._media_artifact(event, view):
            self._refresh_panes()
            return
        message: Message | None = None
        replayed = False
        if isinstance(event, Message):
            message = event
        elif isinstance(event, Task | TaskStatusUpdateEvent):
            if isinstance(event, Task):
                self._set_ext(view, event)
            replayed = view.replayed(event.status)
            if event.status.state != TaskState.TASK_STATE_UNSPECIFIED and not replayed:
                view.state, view.sub_state = event.status.state, sub_state_of(event.metadata)
            if event.status.HasField("message"):
                message = event.status.message
        plan = self.renderer.plan(event)
        self.renderer.render(plan)
        items = [i for i in plan.items if not (replayed and i.kind == "status")]
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
            entry = Entry(f"{who} {item.text}", classes=item.role)
            self._mount(view, entry)
            self.trace.append(f"message · {item.role}")
            if item.role == "agent" and view.unplaced is not None:
                speech, view.unplaced = view.unplaced, None
                self.query_one("#conversation", VerticalScroll).move_child(speech, after=entry)
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
        elif item.kind == "media":
            self._draw_media(item, view)
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
        """A row's state is what the parent relays on its stream (R5.6), or what this
        surface saw itself once the sub-task was opened."""
        state = ref.state or "—"
        if ref.agent is not None:  # on another agent: this surface cannot open it
            return f"{ref.agent.id}/{ref.task_id} · {state} · —"
        view = self.views.get(ref.task_id)
        known = view is not None and view.state != TaskState.TASK_STATE_UNSPECIFIED
        if view and known and (ref.task_id in self._subscribed or ref.state is None):
            state = view.state_name  # opened here: its own stream is the newer word
        goal = view.ext.goal if view and view.ext else "—"
        return f"{short_id(ref.task_id)} · {state} · {goal}"

    def _sync_sub_tasks(self) -> None:
        """One row per sub-task of the open task. The parent's stream carries each row's
        state (R5.6), so no sub-task is followed until it is opened; a local one is read
        once for its goal."""
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
            if ref.agent is None and ref.task_id not in self._read and self.client is not None:
                self._read.add(ref.task_id)
                self.run_worker(self._fetch(ref.task_id), exclusive=False)

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
        (R6.7); nothing once the name is complete (a space follows) or for plain text. A
        surface command taking a path says Tab completes it; pending files are counted."""
        if value.startswith("/") and " " in value:
            name = value[1:].split(" ", 1)[0]
            spec = next((c for c in self.commands if c.name == name), None)
            if spec is not None and name in self.local_commands:
                return Text(f"{spec.description} · Tab completes the path")
            return Text()
        if not value.startswith("/"):
            count = len(self.attachments)
            if not count:
                return Text()
            files = "attachment" if count == 1 else "attachments"
            return Text(f"Enter sends the message with {count} {files}")
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
        if not text and not self.attachments:
            return
        event.input.value = ""
        call = parse_command_text(text, self.local_commands)
        if call is not None:  # a surface command: it runs here and sends nothing
            self.local_commands[call.name](call.arguments.strip())
            self._update_hint()
            return
        self._submit(text)

    def _submit(self, text: str) -> None:
        """Send ``text`` with the pending attachments (a recording among them)."""
        view = self.view
        if view is not None and view.terminal:
            self._notice(f"── task is {view.state_name}; nothing sent")
            return
        self._stop_speaking()  # R4.3: a new message interrupts the reply being spoken
        files = tuple(self.attachments)
        self.attachments.clear()
        self._show_chips()
        self._update_hint()
        turn = self._draw_turn(view, text, files) if view is not None else None
        if self.client is not None:
            self.run_worker(self._send(text, files, turn), exclusive=False)

    def _draw_turn(self, view: TaskView, text: str, files: Sequence[Attachment]) -> Widget:
        """The user's message as sent: each file's line, then the text. Its files get
        their media URLs from the server's echo (``view.pending``)."""
        you = f"you {CHEVRON} "
        indent = " " * len(you)
        if not files:
            entry = Entry(f"{you}{text}", classes="you")
            self._mount(view, entry)
            return entry
        widgets: list[Widget] = []
        for index, attachment in enumerate(files):
            prefix = you if index == 0 else indent
            widgets.append(self._file_widget(attachment, prefix))
        if text:
            widgets.append(Entry(f"{indent}{text}", classes="you"))
        turn = Turn(*widgets)
        self._mount(view, turn)
        view.pending.append(widgets)
        return turn

    def _file_widget(self, attachment: Attachment, prefix: str) -> Widget:
        if attachment.kind == "image":
            size = f" · {human_size(attachment.size)}"
            entry = MediaEntry(
                name=attachment.name,
                media_type=attachment.media_type,
                role="you",
                header=f"{prefix}[image] {attachment.name}{self._dims(attachment)}{size}",
                width=attachment.width,
                height=attachment.height,
                own=True,
                data=attachment.data,
            )
            return entry
        return AudioEntry(
            name=attachment.name,
            media_type=attachment.media_type,
            role="you",
            prefix=prefix,
            duration_ms=attachment.duration_ms,
            voice=attachment.voice,
            transcribing=self._transcribes,
            data=attachment.data,
        )

    @staticmethod
    def _dims(attachment: Attachment) -> str:
        if attachment.width and attachment.height:
            return f" · {attachment.width}\u00d7{attachment.height}"
        return ""

    @property
    def _transcribes(self) -> bool:
        return self.media_params is not None and self.media_params.speech_to_text

    async def _send(
        self, text: str, files: Sequence[Attachment] = (), turn: Widget | None = None
    ) -> None:
        assert self.client is not None
        sent_to = self.task_id
        try:
            async for event in self.client.send(
                user_parts(text, files),
                task_id=self.task_id,
                context_id=self.context_id,
                speak=self.speak_replies and self.voice_output,
            ):
                if not self.is_running:  # shutting down: the screen is being torn down
                    return
                self.apply_event(event)
        except CLIENT_ERRORS as exc:
            reason = self._refusal(exc)
            if files and reason is not None:
                self._refused(text, files, turn, exc, reason)
                return
            self._notice(f"── {exc}")
        # The stream of a message ends once the task parks; what happens next (a
        # sub-task's row, a reply woken by a sub-task) arrives on the task's own
        # SubscribeToTask stream, which stays open until it ends (R5.6).
        task_id = sent_to or (self.stack[0] if self.stack else None)
        if task_id and not self.views[task_id].terminal:
            self._subscribe_once(task_id)

    @staticmethod
    def _error_data(exc: Exception) -> dict[str, str]:
        """An A2A error's data, as text (the media refusal's reason, limit and part)."""
        raw: object = getattr(exc, "data", None) if isinstance(exc, A2AError) else None
        if not isinstance(raw, dict):
            return {}
        items = cast(dict[object, object], raw).items()
        return {str(k): str(v) for k, v in items if v is not None}

    def _refusal(self, exc: Exception) -> str | None:
        """The media refusal's reason, when ``exc`` is one (an ``InvalidParams`` whose data
        names a reason, issue-38 R1.3)."""
        return self._error_data(exc).get("reason")

    def _refused(
        self,
        text: str,
        files: Sequence[Attachment],
        turn: Widget | None,
        exc: Exception,
        reason: str,
    ) -> None:
        """Nothing was sent: the turn goes, the chips and the text come back, and the error
        line names the file and the limit, so the user can remove one and send again."""
        if turn is not None:
            for view in self.views.values():
                view.pending = [w for w in view.pending if not w or w[0].parent is not turn]
            turn.remove()
        self.attachments[:0] = files
        composer = self.query_one("#composer", Input)
        if not composer.value:
            composer.value = text
        data = self._error_data(exc)
        part = data.get("part", "")
        index = int(part) - (1 if text else 0) if part.isdigit() else -1
        detail = str(getattr(exc, "message", exc))
        if 0 <= index < len(files):
            detail = rejection_text(files[index], reason, data.get("limit"), detail)
        self._notice_error(f"✗ not sent: {detail}. Backspace removes it.")
        self._show_chips()
        self._update_hint()

    def _notice_error(self, text: str) -> None:
        if self.view is not None:
            self._mount(self.view, Entry(text, classes="error"))

    # --- attachments (issue-38 R1.2) --------------------------------------------------

    def _attach_file(self, argument: str) -> None:
        """``/attach <path>``: the file becomes a chip once the card's limits allow it."""
        if not argument:
            self._notice("── usage: /attach <path>")
            return
        path = Path(argument).expanduser()
        try:
            attachment = load_attachment(path, self.media_params, self.attachments)
        except AttachRefused as exc:
            self._notice_error(f"✗ not attached: {exc}")
            return
        self.add_attachment(attachment)

    def add_attachment(self, attachment: Attachment) -> None:
        """A chip for the next message (``/attach``, or a recording)."""
        self.attachments.append(attachment)
        self._show_chips()
        self._update_hint()
        self.trace.append(f"attached · {attachment.media_type}")

    def _show_chips(self) -> None:
        chips = self.query_one("#chips", Static)
        chips.display = bool(self.attachments)
        line = Text("attached: ")
        for attachment in self.attachments:
            line.append(f" {chip_text(attachment)} ", style="reverse")
            line.append("  ")
        line.append(" Backspace removes the last")
        chips.update(line)

    def on_composer_empty_backspace(self, event: Composer.EmptyBackspace) -> None:
        if self.attachments:
            removed = self.attachments.pop()
            self.trace.append(f"removed · {removed.name}")
            self._show_chips()
            self._update_hint()

    def _update_hint(self) -> None:
        value = self.query_one("#composer", Input).value
        self.query_one("#hint", Static).update(self._hint(value))

    # --- media from the server (issue-38 R2.4, R6.3) ----------------------------------

    def _media_artifact(self, event: TaskArtifactUpdateEvent, view: TaskView) -> bool:
        """The user's message echo and a transcript are not agent text: they complete
        entries already drawn. True when ``event`` was one of them, or a media artifact
        already drawn."""
        artifact_id = event.artifact.artifact_id
        if artifact_id.startswith(MESSAGE_ARTIFACT):
            if artifact_id not in view.seen:
                view.seen.add(artifact_id)
                self._echo(event, view)
            return True
        if artifact_id.startswith(TRANSCRIPT_ARTIFACT):
            media_id = artifact_id.removeprefix(TRANSCRIPT_ARTIFACT)
            text = "\n".join(p.text for p in event.artifact.parts if p.HasField("text"))
            view.transcripts[media_id] = text
            if media_id in view.audio:
                view.audio[media_id].set_transcript(text)
            self.trace.append("transcript")
            return True
        if any(is_media_part(p) for p in event.artifact.parts):
            # An image or a spoken reply: the task's subscription replays the log the
            # send stream already showed, so draw (and play) each artifact once.
            if artifact_id in view.seen:
                return True
            view.seen.add(artifact_id)
        return False

    def _echo(self, event: TaskArtifactUpdateEvent, view: TaskView) -> None:
        metadata = json_format.MessageToDict(event.artifact.metadata)
        participant = str(metadata.get("participant_id", "") or "")
        media = [p for p in event.artifact.parts if is_media_part(p)]
        task_id = event.task_id
        if participant == self.participant and view.pending:
            files = [w for w in view.pending.pop(0) if isinstance(w, MediaEntry | AudioEntry)]
            for widget, part in zip(files, media, strict=False):
                self._bind(widget, part, view, task_id)
            self.trace.append("message · media stored")
            return
        who = "you" if participant == self.participant else participant or "?"
        prefix = f"{who} {CHEVRON} "
        indent = " " * len(prefix)
        texts = [p.text for p in event.artifact.parts if p.HasField("text")]
        turn = Turn()
        self._mount(view, turn)
        for index, part in enumerate(media):
            meta = self._part_meta(part)
            lead = prefix if index == 0 else indent
            widget: Widget
            if part.media_type in ACCEPTED and ACCEPTED[part.media_type].value == "image":
                dims = f" · {meta.width}\u00d7{meta.height}" if meta.width and meta.height else ""
                size = f" · {human_size(meta.size)}" if meta.size else ""
                widget = MediaEntry(
                    name=part.filename,
                    media_type=part.media_type,
                    role="you",
                    header=f"{lead}[image] {part.filename or 'image'}{dims}{size}",
                    indent=len(indent),
                    own=participant == self.participant,  # their own file: no saved-to line
                )
            else:
                widget = AudioEntry(
                    name=part.filename,
                    media_type=part.media_type,
                    role="you",
                    prefix=lead,
                    duration_ms=meta.duration_ms,
                    voice=bool(meta.voice),
                    transcribing=self._transcribes,
                )
            turn.mount(widget)
            self._bind(widget, part, view, task_id)
        for text in texts:
            turn.mount(Entry(f"{indent if media else prefix}{text}", classes="you"))
        self.trace.append(f"message · {who} · media")

    @staticmethod
    def _part_meta(part: Part) -> MediaPartMetadata:
        try:
            return MediaPartMetadata.model_validate(json_format.MessageToDict(part.metadata))
        except ValidationError:
            return MediaPartMetadata()

    def _bind(self, widget: Widget, part: Part, view: TaskView, task_id: str) -> None:
        """Give an entry its stored medium: the URL, the ids parsed from it, and what the
        server measured. An image is then saved and shown."""
        media_path = self.media_params.media_path if self.media_params else MEDIA_ROUTE
        ids = media_ids(part.url, media_path)
        meta = self._part_meta(part)
        if isinstance(widget, AudioEntry):
            if ids is not None:
                widget.bind(part.url, ids, duration_ms=meta.duration_ms)
                view.audio[ids[1]] = widget
                if ids[1] in view.transcripts:
                    widget.set_transcript(view.transcripts[ids[1]])
            return
        if not isinstance(widget, MediaEntry):
            return
        if ids is None or (task_id and ids[0] != task_id):
            widget.unavailable("not a medium of this task")
            return
        widget.bind(part.url, ids, width=meta.width, height=meta.height)
        self.run_worker(self._save_and_show(widget), exclusive=False)

    def _draw_media(self, item: RenderItem, view: TaskView) -> None:
        """An agent's image (or audio) in a message or artifact."""
        indent = len(f"agent {CHEVRON} ")
        part = Part(url=item.url, media_type=item.media_type, filename=item.name)
        if item.data:
            part.metadata.update(item.data)
        task_id = self.task_id or ""
        for key, candidate in self.views.items():
            if candidate is view:
                task_id = key
        if item.media_type == PCM_MEDIA_TYPE:
            self._speech(item, view, indent)
            return
        widget: Widget
        if item.media_type in ACCEPTED and ACCEPTED[item.media_type].value == "image":
            widget = MediaEntry(
                name=item.name, media_type=item.media_type, role=item.role, indent=indent
            )
        else:
            meta = self._part_meta(part)
            widget = AudioEntry(
                name=item.name,
                media_type=item.media_type,
                role=item.role,
                prefix=" " * indent,
                duration_ms=meta.duration_ms,
            )
        self._mount(view, widget)
        self._bind(widget, part, view, task_id)
        self.trace.append(f"media · {item.media_type}")

    async def _save_and_show(self, entry: MediaEntry) -> None:
        """Save the image to the cache (the user's own bytes, else fetched with the
        participant header) and show it."""
        assert entry.ids is not None
        task_id, media_id = entry.ids
        try:
            path = self.media_cache.cached(task_id, media_id, entry.media_type)
            if path is None:
                data = entry.data if entry.data is not None else await self._download(entry.url)
                path = self.media_cache.write(task_id, media_id, entry.media_type, data)
        except (*CLIENT_ERRORS, MediaCacheError, OSError, ValueError) as exc:
            if self.is_running:
                entry.unavailable(type(exc).__name__ if not str(exc) else str(exc)[:80])
            return
        if self.is_running:
            entry.show(path, self.media_cache, self.image_view)

    async def _download(self, url: str) -> bytes:
        assert self.client is not None
        limit = MAX_FETCH_BYTES
        if self.media_params is not None and self.media_params.max_file_bytes:
            limit = max(self.media_params.max_file_bytes, 1)
        chunks: list[bytes] = []
        total = 0
        async for chunk in self.client.get_media(url):
            total += len(chunk)
            if total > limit:
                raise ValueError(f"larger than {limit} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    def _subscribe_once(self, task_id: str) -> None:
        if self.client is not None and task_id not in self._subscribed:
            self._subscribed.add(task_id)
            self.run_worker(self._subscribe(task_id), exclusive=False)

    async def _subscribe(self, task_id: str) -> None:
        """Follow ``task_id`` until it ends. A subscription refused (a terminal task) or
        dropped falls back to one ``GetTask``; a task still open is followed again."""
        assert self.client is not None
        found = True
        try:
            async for event in self.client.subscribe(task_id):
                if not self.is_running:  # shutting down: the screen is being torn down
                    return
                self.apply_event(event)
        except CLIENT_ERRORS as exc:
            self.trace.append(f"subscription {short_id(task_id)} ended: {exc}")
            found = await self._fetch(task_id)
        view = self.views.get(task_id)
        if self.is_running and found and view is not None and not view.terminal:
            self.set_timer(self.resubscribe_delay, lambda: self._resubscribe(task_id))

    def _resubscribe(self, task_id: str) -> None:
        self._subscribed.discard(task_id)
        self._subscribe_once(task_id)

    async def _fetch(self, task_id: str) -> bool:
        assert self.client is not None
        try:
            task = await self.client.get_task(task_id)
        except CLIENT_ERRORS as exc:
            self.trace.append(f"task {short_id(task_id)} unavailable: {exc}")
            return False
        if self.is_running:
            self.apply_event(task)
        return True

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
                if not self.is_running:  # shutting down: the screen is being torn down
                    return
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
        if action == "toggle_record":
            return self.voice_input
        if action == "toggle_speak":
            return self.voice_output
        if action == "stop_voice":  # shown only while there is something to stop
            return bool(self.recording or self.speaking is not None or self.player.playing)
        return True

    # --- voice (issue-38 R3, R4) ------------------------------------------------------

    @property
    def voice_input(self) -> bool:
        """The card accepts the WAV a recording is."""
        return self.media_params is not None and RECORDING_TYPE in self.media_params.input

    @property
    def voice_output(self) -> bool:
        return self.media_params is not None and self.media_params.text_to_speech

    def on_composer_space_down(self, event: Composer.SpaceDown) -> None:
        now = self.hold.clock()
        self._hold_result(self.hold.tick(now))
        if self.hold.key_down(now) == "start":
            self._start_recording("hold")

    def _hold_result(self, result: str | None) -> None:
        if result == "type-space":
            composer = self.query_one("#composer", Input)
            if not composer.value:  # typed meanwhile: the leading space is not kept
                composer.insert_text_at_cursor(" ")
        elif result == "end" and self.recording == "hold":
            self._stop_recording()

    def on_unmount(self) -> None:
        """Quitting discards an open recording, closing the microphone, and stops the
        reply being spoken."""
        if self.recording:
            self.recording = None
            self.recorder.discard()
        self._stop_speaking()

    def _voice_tick(self) -> None:
        if not self.is_running:  # shutting down: the widgets the tick draws are gone
            return
        if self.hold.active:
            self._hold_result(self.hold.tick(self.hold.clock()))
        if self.recording:
            self._show_recording()
        if self.speaking is not None and self.player.playing:
            self.speaking.streaming(self.player.levels, self.player.played_ms)

    def action_toggle_record(self) -> None:
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording("toggle")

    def _start_recording(self, mode: str) -> None:
        if not self.voice_input:
            self._notice("── voice input unavailable: this agent accepts no WAV audio")
            return
        self._stop_speaking()  # R4.3: a new recording interrupts the reply being spoken
        try:
            self.recorder.start()
        except VoiceUnavailable as exc:
            self._notice(f"── {exc}")
            return
        self.recording = mode
        self._show_recording()
        self.trace.append(f"recording · {mode}")
        self.refresh_bindings()

    def _show_recording(self) -> None:
        bar = self.query_one("#rec", Static)
        bar.display = True
        levels = meter(self.recorder.levels, width=12)
        bar.update(f"● REC  {levels}  {clock(self.recorder.duration_ms)}")
        release = "release Space" if self.recording == "hold" else "F5"
        self.query_one("#hint", Static).update(Text(f"{release} to send · Esc discards"))

    def _stop_recording(self, *, send: bool = True) -> None:
        self.recording = None
        self.query_one("#rec", Static).display = False
        self._update_hint()
        self.refresh_bindings()
        if not send:
            self.recorder.discard()
            self._notice("── recording discarded")
            return
        wav = self.recorder.stop()
        if wav is None:
            self._notice("── nothing recorded (too short or silent)")
            return
        voice = Attachment(
            "voice.wav", RECORDING_TYPE, wav, duration_ms=self.recorder.duration_ms, voice=True
        )
        composer = self.query_one("#composer", Input)
        text, composer.value = composer.value.strip(), ""
        self.attachments.append(voice)
        self.trace.append("recording · sent")
        self._submit(text)

    def action_toggle_speak(self) -> None:
        self.speak_replies = not self.speak_replies
        self._refresh_panes()

    def action_stop_voice(self) -> None:
        """Escape: discard a recording, or stop the reply being spoken."""
        if self.recording:
            self._stop_recording(send=False)
        else:
            self._stop_speaking()

    def _stop_speaking(self) -> None:
        if self.player.playing:
            self.player.stop()

    def _speech(self, item: RenderItem, view: TaskView, indent: int) -> None:
        """A spoken reply: its line, played at once when spoken replies are on."""
        media_id = str((item.data or {}).get("mediaId", ""))
        entry = SpeechEntry(item.url, media_id=media_id, indent=indent)
        self._mount(view, entry)
        view.unplaced = entry
        self.trace.append("speech")
        if self.speak_replies and self.client is not None:
            self.run_worker(self._play_speech(entry), exclusive=False)

    def on_speech_entry_replay(self, event: SpeechEntry.Replay) -> None:
        if self.client is not None:
            self.run_worker(self._play_speech(event.entry), exclusive=False)

    async def _play_speech(self, entry: SpeechEntry) -> None:
        """Stream the reply's PCM to the speakers as it arrives (R4.1); a broken stream is
        "interrupted" (R4.3) and Enter replays the URL from its start."""
        assert self.client is not None
        self.speaking = entry
        entry.streaming([], 0)
        self.query_one("#hint", Static).update(Text("speaking… Esc stops"))
        self.refresh_bindings()
        try:
            # ``play`` stops a reply already playing (one at a time, R4.3).
            played = await self.player.play(self.client.get_media(entry.url), SPEECH_FORMAT)
        except VoiceUnavailable as exc:
            entry.unavailable(str(exc))
        except (*CLIENT_ERRORS, OSError):
            entry.interrupted()
        else:
            if played.stopped:
                entry.stopped(played.played_ms)
            else:
                entry.done(played.played_ms)
        finally:
            if self.speaking is entry:
                self.speaking = None
            if self.is_running:
                self._update_hint()
                self.refresh_bindings()

    def on_audio_entry_play(self, event: AudioEntry.Play) -> None:
        self.run_worker(self._play_audio(event.entry), exclusive=False)

    async def _play_audio(self, entry: AudioEntry) -> None:
        """Enter on an audio entry: a WAV plays here; another type is saved and named."""
        try:
            data = entry.data
            if data is None:
                data = await self._download(entry.url)
            if entry.media_type == RECORDING_TYPE:
                pcm, fmt = wav_pcm(data)
                await self.player.play(once(pcm), fmt)  # stops a reply being spoken
                return
            if entry.ids is None:
                raise ValueError("not stored yet")
            path = self.media_cache.write(*entry.ids, entry.media_type, data)
        except VoiceUnavailable as exc:
            self._notice(f"── {exc}")
            return
        except (*CLIENT_ERRORS, MediaCacheError, OSError, ValueError) as exc:
            self._notice(f"── cannot play {entry.name_text}: {exc}")
            return
        self._notice(f"── {entry.name_text} plays outside the TUI; saved to {path}")

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
                if not self.is_running:  # shutting down: the screen is being torn down
                    return
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


async def run_tui(url: str, *, participant: str, hold_ms: int | None = None) -> int:
    image_view = graphics_image_view()  # asks the terminal before Textual owns it
    client = await SdkClient.connect(url, participant=participant)
    try:
        await HarnessApp(
            client, url=url, participant=participant, image_view=image_view, hold_ms=hold_ms
        ).run_async()
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
    "Turn",
    "run_tui",
]
