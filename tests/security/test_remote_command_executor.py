"""Abuse case 10 (issue-25): a remote command executor declared by a plugin receives only
the command it implements, and only after the redactor has scrubbed the context; a
command-owned hook that also claims other points is skipped, never registered unfiltered."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
from pydantic import HttpUrl

from tests.fixtures.plugins.registrar import RecordingRegistrar
from tiny_harness.harness.commands import (
    CommandInvokedIn,
    CommandRegistry,
    CommandResult,
    CommandSpec,
    TaskSnapshot,
)
from tiny_harness.harness.core import Role
from tiny_harness.harness.hooks import (
    HookManager,
    HookPoint,
    Operation,
    OperationRunner,
    Phase,
    Providers,
)
from tiny_harness.harness.plugins import (
    CommandDef,
    ComponentKind,
    HookDef,
    Plugin,
    PluginLoader,
    PluginManifest,
)
from tiny_harness.harness.security import Redactor

SECRET = "sk-live-0123456789abcdefghijklmnop"
MANIFEST = PluginManifest.model_validate(
    {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "ops"}
)


def invoked(name: str, arguments: str) -> CommandInvokedIn:
    return CommandInvokedIn(
        task_id="t-1",
        correlation_id="c-1",
        name=name,
        arguments=arguments,
        sender="alice",
        sender_role=Role.REPORTER,
        task=TaskSnapshot(id="t-1", name="Audit", state="INPUT_REQUIRED"),
    )


def remote_stub(seen: list[dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = cast(dict[str, object], json.loads(request.content))
        seen.append(body)
        params = cast(dict[str, object], body["params"])
        context = cast(dict[str, object], params["context"])
        answered = {**context, "result": {"reply": "deployed"}}
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"context": answered}}
        )

    return httpx.MockTransport(handler)


async def test_a_remote_command_executor_sees_only_its_own_command_scrubbed(
    tmp_path: Path,
) -> None:
    seen: list[dict[str, object]] = []
    transport = remote_stub(seen)
    hooks = HookManager()
    commands = CommandRegistry(hooks)
    commands.register(
        CommandSpec(name="status", description="d"), lambda c: CommandResult(reply="ok")
    )
    loader = PluginLoader(
        hook_manager=hooks,
        registrar=RecordingRegistrar(),
        data_root=tmp_path,
        providers=Providers(http_client_factory=lambda: httpx.AsyncClient(transport=transport)),
        commands=commands,
    )
    rpc = HookDef(
        name="deploy-rpc", url=HttpUrl("https://hooks.example/rpc"), points=("command.invoked.in",)
    )
    report = await loader.load(
        Plugin(
            manifest=MANIFEST,
            hooks=(rpc,),
            commands=(CommandDef(name="deploy", description="Deploy", hook="deploy-rpc"),),
        )
    )
    assert report.loaded_ids(ComponentKind.COMMAND) == ("deploy",)
    runner = OperationRunner(hooks, Redactor(secrets=[SECRET]))

    other = await runner.run_in(Operation.COMMAND_INVOKED, invoked("status", SECRET))
    assert other.result == CommandResult(reply="ok")
    assert seen == []  # another command's arguments never reach the remote executor

    mine = await runner.run_in(Operation.COMMAND_INVOKED, invoked("deploy", f"prod {SECRET}"))
    assert mine.result == CommandResult(reply="deployed")
    (call,) = seen
    assert call["method"] == "command.invoked.in"
    assert SECRET not in json.dumps(call)
    context = cast(dict[str, object], cast(dict[str, object], call["params"])["context"])
    assert context["name"] == "deploy"


async def test_a_command_owned_hook_with_extra_points_is_skipped(tmp_path: Path) -> None:
    seen: list[dict[str, object]] = []
    transport = remote_stub(seen)
    hooks = HookManager()
    loader = PluginLoader(
        hook_manager=hooks,
        registrar=RecordingRegistrar(),
        data_root=tmp_path,
        providers=Providers(http_client_factory=lambda: httpx.AsyncClient(transport=transport)),
        commands=CommandRegistry(hooks),
    )
    wide = HookDef(
        name="deploy-rpc",
        url=HttpUrl("https://hooks.example/rpc"),
        points=("command.invoked.in", "llm.invoked.pre"),
    )
    report = await loader.load(
        Plugin(
            manifest=MANIFEST,
            hooks=(wide,),
            commands=(CommandDef(name="deploy", description="Deploy", hook="deploy-rpc"),),
        )
    )
    assert report.loaded == ()
    assert [(s.kind, s.id) for s in report.skipped] == [(ComponentKind.COMMAND, "deploy")]
    for operation in (Operation.COMMAND_INVOKED, Operation.LLM_INVOKED):
        for phase in Phase:
            assert hooks.executors_for(HookPoint(operation=operation, phase=phase)) == []
