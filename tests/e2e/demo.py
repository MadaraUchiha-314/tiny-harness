"""The demo as separate server and worker processes, driven through the A2A client (T4, T12).

Each ``Demo`` gets its own state directory, port and Temporal task queue, so a run never
shares tasks with a leftover worker. Secrets stay in the environment: the processes
inherit it and nothing here reads a key. Evidence written by the tests is redacted of
every secret value before it leaves the process.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
from a2a.client import Client, ClientConfig, create_client
from a2a.types import GetTaskRequest, Message, Part, SendMessageRequest, StreamResponse, TaskState
from a2a.types import Role as A2ARole
from google.protobuf import json_format, struct_pb2

from tiny_harness.interaction.a2ui import A2UI_MEDIA_TYPE, Action
from tiny_harness.jsontypes import JsonObject

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "examples" / "demo"
LOGS = Path.home() / ".cache" / "tiny-harness-logs" / "e2e"
SECRET_VARIABLES = ("TEMPORAL_API_KEY", "OPENAI_API_KEY", "TINY_HARNESS_PUSH_KEY")

COMPLAINT = (
    "Refund order #48213: the customer says the blender arrived cracked. "
    "Check the order and propose a resolution."
)
REPLY = (
    "Ship a replacement for order #48213 to the address on the order, 14 Harbour Lane, "
    "Portsea. The customer reported the crack on 2026-10-06, the day it was delivered, "
    "and the other open order #48377 is unrelated. You have everything you need: go ahead."
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def redact(text: str) -> str:
    for name in SECRET_VARIABLES:
        value = os.environ.get(name)
        if value:
            text = text.replace(value, f"<{name}>")
    return text


@dataclass
class Event:
    at: float
    kind: str
    state: int | None
    text: str
    raw: JsonObject

    def line(self) -> str:
        state = TaskState.Name(self.state) if self.state is not None else ""
        return f"[{self.at:6.1f}s] {self.kind:<14} {state:<24} {self.text}"


@dataclass
class Demo:
    """One demo instance: its config file, state directory and processes."""

    root: Path
    port: int
    task_queue: str
    config: Path = field(init=False)
    server: subprocess.Popen[bytes] | None = None
    worker: subprocess.Popen[bytes] | None = None
    workers_started: int = 0
    started: float = field(default_factory=time.monotonic)

    @classmethod
    def create(cls, name: str) -> Demo:
        suffix = uuid.uuid4().hex[:8]
        root = LOGS / f"{name}-{suffix}"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True)
        demo = cls(root=root, port=free_port(), task_queue=f"tiny-harness-e2e-{suffix}")
        demo.config = root / "config.toml"
        demo.config.write_text(demo.config_text())
        return demo

    def config_text(self) -> str:
        """The demo's config with this run's paths, port and task queue (no secrets)."""
        base = f"http://127.0.0.1:{self.port}"
        return "\n".join(
            [
                f'plugins = ["{DEMO}"]',
                "[temporal]",
                'address = "tiny-harness.gtebu.tmprl.cloud:7233"',
                'namespace = "tiny-harness.gtebu"',
                f'task_queue = "{self.task_queue}"',
                "tls = true",
                "search_attributes = false",
                "[openai]",
                'model = "gpt-6.1-sol"',
                'timeout = "PT120S"',
                "max_output_tokens = 2000",
                "[server]",
                f'bind = "127.0.0.1:{self.port}"',
                f'base_url = "{base}"',
                "[heartbeat]",
                'interval = "PT30S"',
                "[store]",
                f'sqlite_path = "{self.root / "state" / "tiny-harness.sqlite3"}"',
                "[o11y]",
                'log_level = "INFO"',
                f'trace_file = "{self.trace_file}"',
                "",
            ]
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def trace_file(self) -> Path:
        return self.root / "state" / "trace.jsonl"

    @property
    def plugin_data(self) -> Path:
        return self.root / "state" / "plugin-data" / "demo-support"

    @property
    def ledger_file(self) -> Path:
        return self.plugin_data / "orders-ledger.jsonl"

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    # --- processes -----------------------------------------------------------------------

    def _spawn(self, verb: list[str], log: str) -> subprocess.Popen[bytes]:
        handle = (self.root / log).open("ab")
        return subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys; from tiny_harness.service.cli import main; sys.exit(main())",
                "--config",
                str(self.config),
                *verb,
            ],
            cwd=REPO,
            env=os.environ,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )

    async def start_server(self, *, with_worker: bool = False) -> None:
        verb = ["serve", "--with-worker"] if with_worker else ["serve"]
        self.server = self._spawn(verb, "server.log")
        async with httpx.AsyncClient(timeout=2) as http:
            for _ in range(180):
                if self.server.poll() is not None:
                    raise RuntimeError(f"server exited: {self.read_log('server.log')[-2000:]}")
                try:
                    response = await http.get(f"{self.base_url}/.well-known/agent-card.json")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
        raise RuntimeError("the server never came up")

    def start_worker(self) -> None:
        self.workers_started += 1
        self.worker = self._spawn(["worker"], f"worker-{self.workers_started}.log")

    def kill_worker(self) -> float:
        """``kill -9`` the worker and its MCP subprocesses; returns the kill time."""
        assert self.worker is not None
        at = self.elapsed()
        self.worker.send_signal(signal.SIGKILL)
        self.worker.wait(10)
        self.worker = None
        return at

    def stop(self) -> None:
        for proc in (self.worker, self.server):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(15)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.worker = self.server = None

    def read_log(self, name: str) -> str:
        path = self.root / name
        return path.read_text(errors="replace") if path.exists() else ""

    # --- evidence ------------------------------------------------------------------------

    def ledger(self) -> list[JsonObject]:
        if not self.ledger_file.exists():
            return []
        return [
            cast(JsonObject, json.loads(line))
            for line in self.ledger_file.read_text().splitlines()
            if line.strip()
        ]

    def spans(self) -> list[JsonObject]:
        if not self.trace_file.exists():
            return []
        return [
            cast(JsonObject, json.loads(line))
            for line in self.trace_file.read_text().splitlines()
            if line.strip()
        ]

    def evidence_dir(self) -> Path | None:
        target = os.environ.get("TINY_HARNESS_E2E_EVIDENCE")
        return Path(target) if target else None

    def write_evidence(self, name: str, text: str) -> None:
        """Redacted; to the run dir, and to ``TINY_HARNESS_E2E_EVIDENCE`` when that is set."""
        text = redact(text)
        (self.root / name).write_text(text)
        target = self.evidence_dir()
        if target is not None:
            target.mkdir(parents=True, exist_ok=True)
            (target / name).write_text(text)


# --- the A2A client side --------------------------------------------------------------------


def user_message(
    text: str, *, context_id: str, task_id: str | None = None, participant: str = "alice"
) -> Message:
    msg = Message(
        message_id=uuid.uuid4().hex,
        context_id=context_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(text=text)],
    )
    if task_id is not None:
        msg.task_id = task_id
    msg.metadata.update({"participant_id": participant})
    return msg


def action_message(
    action: Action, *, task_id: str, context_id: str, participant: str = "alice"
) -> Message:
    value = struct_pb2.Value()
    value.struct_value.update(action.payload())
    msg = Message(
        message_id=uuid.uuid4().hex,
        task_id=task_id,
        context_id=context_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(data=value, media_type=A2UI_MEDIA_TYPE)],
    )
    msg.metadata.update({"participant_id": participant})
    return msg


def confirm_action(parts: list[JsonObject]) -> Action | None:
    """The ``confirm`` button of the card the agent emitted, with its first choice picked."""
    surface_id: str | None = None
    button: JsonObject | None = None
    choice: object = None
    for part in parts:
        update = cast(JsonObject | None, part.get("updateComponents"))
        if not isinstance(update, dict):
            continue
        surface_id = cast(str, update.get("surfaceId"))
        for component in cast(list[JsonObject], update.get("components", [])):
            if component.get("component") == "Button" and button is None:
                button = component
            if component.get("component") == "ChoicePicker" and choice is None:
                options = cast(list[JsonObject], component.get("options", []))
                choice = options[0].get("value") if options else None
    if surface_id is None or button is None:
        return None
    event = cast(JsonObject, cast(JsonObject, button.get("action", {})).get("event", {}))
    return Action(
        name=cast(str, event.get("name", "confirm")),
        surfaceId=surface_id,
        sourceComponentId=str(button["id"]),
        timestamp=datetime.now(UTC).isoformat(),
        context={"choice": choice} if isinstance(choice, str) else {},
    )


class Driver:
    """Sends messages for one task and keeps the transcript."""

    def __init__(self, demo: Demo, *, context_id: str | None = None) -> None:
        self.demo = demo
        self.context_id = context_id or f"ctx-{uuid.uuid4().hex[:8]}"
        self.task_id: str | None = None
        self.events: list[Event] = []
        self.a2ui_parts: list[JsonObject] = []
        self._http: httpx.AsyncClient | None = None
        self._client: Client | None = None

    async def client(self) -> Client:
        if self._client is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(300, read=None))
            self._client = await create_client(
                self.demo.base_url,
                client_config=ClientConfig(
                    httpx_client=self._http,
                    streaming=True,
                    supported_protocol_bindings=["JSONRPC"],
                ),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        if self._http is not None:
            await self._http.aclose()

    def _record(self, response: StreamResponse) -> Event:
        raw = cast(JsonObject, json_format.MessageToDict(response))
        at = self.demo.elapsed()
        if response.HasField("task"):
            self.task_id = response.task.id
            event = Event(at, "task", response.task.status.state, response.task.id, raw)
        elif response.HasField("status_update"):
            status = response.status_update.status
            text = (
                "".join(p.text for p in status.message.parts if p.HasField("text"))
                if status.HasField("message")
                else ""
            )
            event = Event(at, "status_update", status.state, text, raw)
        elif response.HasField("artifact_update"):
            artifact = response.artifact_update.artifact
            for part in artifact.parts:
                if part.media_type == A2UI_MEDIA_TYPE and part.HasField("data"):
                    self.a2ui_parts.append(cast(JsonObject, json_format.MessageToDict(part.data)))
            event = Event(at, "artifact_update", None, artifact.name, raw)
        else:
            event = Event(at, "message", None, "", raw)
        self.events.append(event)
        return event

    async def send(
        self, message: Message, *, on_event: Callable[[Event], None] | None = None
    ) -> int | None:
        """Stream one message's responses; returns the last task state seen."""
        state: int | None = None
        client = await self.client()
        async for response in client.send_message(SendMessageRequest(message=message)):
            event = self._record(response)
            if on_event is not None:
                on_event(event)
            if event.state is not None:
                state = event.state
        return state

    async def run(
        self,
        *,
        on_event: Callable[[Event], None] | None = None,
        reply: str = REPLY,
        act_on_card: bool = True,
        max_rounds: int = 4,
    ) -> int | None:
        """The whole conversation: the complaint, then a reply per INPUT_REQUIRED."""
        state = await self.send(
            user_message(COMPLAINT, context_id=self.context_id), on_event=on_event
        )
        rounds = 0
        while state == TaskState.TASK_STATE_INPUT_REQUIRED and rounds < max_rounds:
            rounds += 1
            assert self.task_id is not None
            action = confirm_action(self.a2ui_parts) if act_on_card and rounds == 1 else None
            if action is not None:
                message = action_message(action, task_id=self.task_id, context_id=self.context_id)
            else:
                message = user_message(reply, context_id=self.context_id, task_id=self.task_id)
            state = await self.send(message, on_event=on_event)
        return state

    async def final_task(self) -> JsonObject:
        assert self.task_id is not None
        client = await self.client()
        task = await client.get_task(GetTaskRequest(id=self.task_id))
        return cast(JsonObject, json_format.MessageToDict(task))

    def transcript(self) -> str:
        return "\n".join(e.line() for e in self.events) + "\n"


__all__ = [
    "COMPLAINT",
    "REPLY",
    "Demo",
    "Driver",
    "Event",
    "action_message",
    "confirm_action",
    "redact",
    "user_message",
]
