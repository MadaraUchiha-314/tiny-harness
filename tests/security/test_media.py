"""T8 (issue-38): media at the trust boundaries.

Every path that turns an external A2A message into workflow input runs the media guard
before redaction (design critic 5): a new turn extracts, a control refuses files, and a
remote agent's or a channel's delivery drops them with a note. The test that enumerates
the ingress paths reads the source, so a new path cannot skip the guard unnoticed.
"""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from a2a.client.client import Client as A2AClient
from a2a.server.context import ServerCallContext
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils.errors import InvalidParamsError
from temporalio.client import Client
from temporalio.testing import ActivityEnvironment

from tests.fixtures import media as fx
from tests.integration.durable.conftest import Harness
from tests.integration.durable.test_complete import control
from tiny_harness.harness.agents import RemoteAgent
from tiny_harness.harness.core import HarnessTask, Participant, TaskExtensionData
from tiny_harness.harness.core import Role as TaskRole
from tiny_harness.harness.entities import EntityKind, EntityRef, RegistryEntry
from tiny_harness.service.a2a import HarnessExecutor, PollingEventBridge
from tiny_harness.service.a2a.task_store import PARTICIPANT_STATE_KEY
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.models import PushIn, RemoteTaskIn, WorkflowConfig

ROOT = Path(__file__).resolve().parents[2]
NOTE = "[remote agent sent a image/png file; files from remote agents are not supported]"


class NoClient:
    """A Temporal client that fails the test if anything reaches the workflow."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the workflow was reached ({name}) with a refused message")


def executor() -> HarnessExecutor:
    client = cast(Client, NoClient())
    return HarnessExecutor(
        client,
        task_queue="tq",
        bridge=PollingEventBridge(client),
        config=WorkflowConfig(search_attributes=False),
    )


def alice() -> ServerCallContext:
    context = ServerCallContext()
    context.state[PARTICIPANT_STATE_KEY] = "alice"
    return context


def task_of_alice() -> Task:
    ext = TaskExtensionData(
        name="n",
        goal="g",
        participants=(Participant(id="alice", kind="human", role=TaskRole.REPORTER),),
    )
    return HarnessTask.new("t-1", "ctx-1", ext).proto


def with_image(*parts: Part) -> Message:
    image = Part(raw=fx.png(4, 4), media_type="image/png", filename="photo.png")
    return Message(message_id="m-1", role=Role.ROLE_USER, parts=[*parts, image])


# --- a control carries no files --------------------------------------------------------------


async def test_control_with_file_refused() -> None:
    message = control(task_id="t-1")
    message.parts.append(with_image().parts[0])
    with pytest.raises(InvalidParamsError) as caught:
        async for _ in executor().control(task_of_alice(), message, alice()):
            pass
    assert "controls carry no files" in caught.value.message
    assert getattr(caught.value, "data", None) == {"reason": "files_not_accepted"}


# --- remote agents' deliveries drop files ------------------------------------------------------


class Peer(RemoteAgent):
    """A remote agent whose task status message carries a file part."""

    def __init__(self) -> None:
        card = AgentCard(name="peer", capabilities=AgentCapabilities(push_notifications=True))
        super().__init__(
            EntityRef(kind=EntityKind.AGENT, id="peer", version=None),
            card,
            client=cast(A2AClient, None),
            follow_interval=timedelta(seconds=1),
        )

    def task(self) -> Task:
        status = TaskStatus(state=TaskState.TASK_STATE_COMPLETED)
        status.message.CopyFrom(with_image(Part(text="here is the chart")))
        return Task(id="r-1", status=status)

    async def get_task(self, task_id: str, *, participant: str | None = None) -> Task:
        return self.task()

    async def subscribe(
        self, task_id: str, *, extensions: Sequence[str] = (), participant: str | None = None
    ) -> AsyncIterator[Task]:
        yield self.task()


async def test_push_file_parts_dropped() -> None:
    """A push is a doorbell: what it may apply is ids and a claimed state, never parts.
    The remote task it leads the stand-in to fetch has its file parts dropped, with a
    note, before its text reaches history."""
    assert set(PushIn.model_fields) == {"token_digest", "remote_task_id", "claimed_state"}
    h = await Harness([]).bind()
    await h.registry.add(RegistryEntry(ref=Peer().ref, instance=Peer()))
    acts = Activities(h.engine)
    out = await ActivityEnvironment().run(
        acts.get_remote_task,
        RemoteTaskIn(task_id="t-1.1", correlation_id="c", agent="peer", remote_task_id="r-1"),
    )
    assert out.text == f"here is the chart\n{NOTE}"


async def test_remote_follow_results_drop_file_parts() -> None:
    from tiny_harness.service.durable.activities import remote_text

    assert await remote_text(with_image(Part(text="done"))) == f"done\n{NOTE}"


# --- every ingress is guarded ----------------------------------------------------------------

INGRESS_MARKERS = frozenset(
    {
        # a message becomes workflow input
        "execute_update",
        "execute_update_with_start_workflow",
        # a remote agent's content is read
        "send_message",
        "subscribe",
        "get_task",
        # a channel's messages are read
        "receive",
    }
)

INGRESS: dict[str, str] = {
    # SendMessage: ``execute`` guards, then delivers through this
    "service/a2a/executor.py::HarnessExecutor._update_with_start": "extract",
    "service/a2a/executor.py::HarnessExecutor.control": "refuse",
    "service/durable/activities.py::Activities.poll_channels": "drop",
    "service/durable/activities.py::Activities.get_remote_task": "drop",
    "service/durable/activities.py::_remote_turn": "drop",
    "service/durable/activities.py::_first_change": "drop",
}
"""Each function that turns an external A2A message into workflow input, and its mode."""

DOORBELLS: dict[str, str] = {
    "service/a2a/push.py::PushReceiver.receive": (
        "a push applies ids and a claimed state only; the remote task it leads to is read "
        "by get_remote_task, which drops files"
    ),
    "service/a2a/app.py::build_route_groups": "push_view forwards to PushReceiver.receive",
}
"""Functions that carry a marker but apply no message content of their own."""


def _functions(tree: ast.Module) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    found: dict[str, ast.AsyncFunctionDef | ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    found[f"{node.name}.{item.name}"] = item
    return found


def _called(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _marker(call: ast.Call) -> bool:
    """A method call named like an ingress (``handle.execute_update``,
    ``agent.subscribe``, ``channel.receive``); an ASGI ``receive()`` is no method."""
    return isinstance(call.func, ast.Attribute) and call.func.attr in INGRESS_MARKERS


def _guard_mode(call: ast.Call) -> str | None:
    if _name(call) != "guard":
        return None
    for keyword in call.keywords:
        if keyword.arg == "allow" and isinstance(keyword.value, ast.Constant):
            return str(keyword.value.value)
    return None


def _guarding(functions: dict[str, ast.AsyncFunctionDef | ast.FunctionDef]) -> dict[str, str]:
    """Each function's guard mode: it calls ``guard(allow=<mode>)``, or (transitively) a
    function of the same module that does."""
    modes: dict[str, str] = {}
    for qualified, node in functions.items():
        for call in _called(node):
            if (mode := _guard_mode(call)) is not None:
                modes[qualified.rsplit(".", 1)[-1]] = mode
    changed = True
    while changed:
        changed = False
        for qualified, node in functions.items():
            short = qualified.rsplit(".", 1)[-1]
            if short in modes:
                continue
            for call in _called(node):
                if _name(call) in modes:
                    modes[short] = modes[_name(call)]
                    changed = True
                    break
    return modes


def _mode(
    qualified: str,
    functions: dict[str, ast.AsyncFunctionDef | ast.FunctionDef],
    modes: dict[str, str],
) -> str | None:
    """A function's own guard mode, else the one mode all its callers in the module guard
    with (``execute`` guards, then calls ``_update_with_start``)."""
    short = qualified.rsplit(".", 1)[-1]
    if short in modes:
        return modes[short]
    callers = {
        caller.rsplit(".", 1)[-1]
        for caller, node in functions.items()
        if any(_name(c) == short for c in _called(node))
    }
    found = {modes.get(caller) for caller in callers}
    return found.pop() if len(found) == 1 else None


def test_every_ingress_guarded() -> None:
    package = ROOT / "tiny_harness"
    seen: dict[str, str | None] = {}
    for path in sorted((package / "service").rglob("*.py")):
        relative = path.relative_to(package).as_posix()
        tree = ast.parse(path.read_text())
        functions = _functions(tree)
        modes = _guarding(functions)
        for qualified, node in functions.items():
            if any(_marker(c) for c in _called(node)):
                seen[f"{relative}::{qualified}"] = _mode(qualified, functions, modes)
    unknown = sorted(set(seen) - set(INGRESS) - set(DOORBELLS))
    assert not unknown, f"a new ingress path must run media.intake.guard: {unknown}"
    assert set(INGRESS) <= set(seen), sorted(set(INGRESS) - set(seen))
    wrong = {name: (seen[name], mode) for name, mode in INGRESS.items() if seen[name] != mode}
    assert not wrong, f"(guarded with, expected): {wrong}"
