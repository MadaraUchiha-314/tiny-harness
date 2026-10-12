"""Feature: Built-in commands
Requirement: docs/specs/issue-25/requirements.md#R6a

The built-in plugin's ``/model``, ``/effort``, ``/sub-task`` and ``/status`` run through
the same ``command.invoked`` chain as any command: a plugin may override one, a ``pre``
hook may refuse one, and a remote body that fails changes nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from a2a.types import TaskState
from pydantic import HttpUrl
from temporalio.testing import WorkflowEnvironment

from tests.fixtures.plugins.registrar import RecordingRegistrar
from tests.integration.durable.conftest import (
    Harness,
    awaiting_next_message,
    close,
    message,
    parked,
    send,
    start,
    task,
    until,
)
from tiny_harness.harness.commands import register_builtin_commands, register_role_policy
from tiny_harness.harness.core import HarnessTask, Role, SubState
from tiny_harness.harness.hooks import Providers
from tiny_harness.harness.models import ModelCatalog, scripted
from tiny_harness.harness.persistence import TaskRecord
from tiny_harness.harness.plugins import (
    CommandDef,
    ComponentKind,
    HookDef,
    Plugin,
    PluginLoader,
    PluginManifest,
)
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")

CATALOG = ModelCatalog(default="model-a", selectable=("model-a", "model-b"))
MANIFEST = PluginManifest.model_validate(
    {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "ops"}
)


def ids() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    return f"tq-{suffix}", f"t-{suffix}"


async def with_builtins(h: Harness) -> Harness:
    """The harness as ``build_runtime`` assembles it: the role policy and the built-ins."""
    h.engine.catalog = CATALOG
    register_role_policy(h.hooks)
    register_builtin_commands(h.commands, CATALOG)
    return await h.bind()


def replied(text: str) -> Callable[[HarnessTask], bool]:
    def check(t: HarnessTask) -> bool:
        return t.proto.status.message.parts[0].text.startswith(text)

    return check


async def test_sub_task_creates_a_linked_conversation_task_and_replies_with_its_id(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Built-in commands
    Requirement: docs/specs/issue-25/requirements.md#R9

    Scenario: /sub-task creates a linked conversation task and replies with its id
        Given a conversation task awaiting the next message
        When the reporter sends "/sub-task check the ledger"
        Then a sub-task exists in the same context, linked to the task as its parent
        And its goal is the description and the sender is its reporter
        And it waits INPUT_REQUIRED awaiting the next message, without a model call
        And the reply names the new task's id and carries it as task_ref
        And "/sub-task" with no description replies with the usage and creates nothing
    """
    h = await with_builtins(Harness([scripted("Refunded.")]))
    tq, tid = ids()
    child_id = f"{tid}.1"
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await awaiting_next_message(handle)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/sub-task", task_id=tid, message_id="m2")
        )
        usage = await until(handle, replied("Usage: /sub-task <description>"))
        assert usage.ext.sub_tasks == ()
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox,
            message("/sub-task check the ledger", task_id=tid, message_id="m3"),
        )
        parent = await until(handle, lambda t: len(t.ext.sub_tasks) == 1)
        assert parent.proto.status.message.parts[0].text.endswith(f"Created sub-task {child_id}.")
        assert parent.state == TaskState.TASK_STATE_INPUT_REQUIRED
        child = env.client.get_workflow_handle_for(TaskWorkflow.run, child_id)
        child_task = await until(child, parked(SubState.AWAITING_NEXT_MESSAGE))
        assert child_task.ext.goal == "check the ledger"
        assert child_task.lifecycle == "conversation"
        assert child_task.proto.context_id == parent.proto.context_id
        assert [r.task_id for r in child_task.ext.parent_tasks] == [tid]
        reporter = child_task.ext.participants[0]
        assert (reporter.id, reporter.role) == ("alice", Role.REPORTER)
        await close(handle)
    assert len(h.llm.requests) == 1


async def test_model_and_effort_commands_change_the_next_model_request(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Built-in commands
    Requirement: docs/specs/issue-25/requirements.md#R7

    Scenario: /model and /effort sent as commands change the next model request
        Given a conversation task on the default model awaiting the next message
        When the reporter sends "/model model-b" and then "/effort high"
        Then each reply confirms the choice and the task records it, persisted
        And "/model evil-model" is refused and leaves model-b in place
        When the reporter then sends an ordinary message
        Then that turn's request carries model-b and high
    """
    h = await with_builtins(Harness([scripted("Refunded."), scripted("Done.")]))
    tq, tid = ids()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await awaiting_next_message(handle)
        for i, text in enumerate(("/model model-b", "/effort high", "/model evil-model")):
            await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
                TaskWorkflow.inbox, message(text, task_id=tid, message_id=f"c{i}")
            )
        refused = await until(handle, replied("refused:"))
        assert (refused.ext.model, refused.ext.reasoning_effort) == ("model-b", "high")
        record = await h.store.get(TaskRecord, tid)
        assert record is not None
        assert HarnessTask(record.task).ext.reasoning_effort == "high"
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("and the receipt?", task_id=tid, message_id="m2")
        )
        await until(handle, replied("Done."))
        await close(handle)
    first, second = h.llm.requests
    assert (first.model, first.reasoning_effort) == ("model-a", None)
    assert (second.model, second.reasoning_effort) == ("model-b", "high")


async def test_a_plugin_command_overrides_a_built_in_and_a_pre_hook_can_refuse_it(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Built-in commands
    Requirement: docs/specs/issue-25/requirements.md#R6a

    Scenario: A plugin command overrides a built-in and a pre hook can refuse it
        Given the built-in commands
        And an operator plugin whose commands.json declares "status" with its own body
        And whose hooks.json has an ordinary command.invoked.pre hook refusing "/sub-task"
        When the reporter sends "/status"
        Then the plugin's body answers instead of the built-in
        When the reporter sends "/sub-task take notes"
        Then the reply is the pre hook's refusal and no sub-task is created
    """
    h = await with_builtins(Harness([scripted("Refunded.")]))
    loader = PluginLoader(
        hook_manager=h.hooks,
        registrar=RecordingRegistrar(),
        data_root=tmp_path,
        commands=h.commands,
    )
    plugin = Plugin(
        manifest=MANIFEST,
        hooks=(
            HookDef(
                name="status-body",
                import_path="tests.fixtures.plugins.hooks:status",
                points=("command.invoked.in",),
            ),
            HookDef(
                name="no-sub-tasks",
                import_path="tests.fixtures.plugins.hooks:no_sub_tasks",
                points=("command.invoked.pre",),
            ),
        ),
        commands=(CommandDef(name="status", description="Plugin status", hook="status-body"),),
    )
    report = await loader.load(plugin, override=True)
    assert report.loaded_ids(ComponentKind.COMMAND) == ("status",)
    assert report.loaded_ids(ComponentKind.HOOK) == ("no-sub-tasks",)
    tq, tid = ids()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        await awaiting_next_message(handle)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/status", task_id=tid, message_id="m2")
        )
        await until(handle, replied(f"plugin status: {tid}"))
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/sub-task take notes", task_id=tid, message_id="m3")
        )
        refused = await until(handle, replied("refused: sub-tasks are disabled here"))
        assert refused.ext.sub_tasks == ()
        assert refused.state == TaskState.TASK_STATE_INPUT_REQUIRED
        await close(handle)
    assert len(h.llm.requests) == 1


async def test_a_remote_command_executor_that_fails_leaves_the_task_unchanged(
    env: WorkflowEnvironment, tmp_path: Path
) -> None:
    """
    Feature: Built-in commands
    Requirement: docs/specs/issue-25/requirements.md#R6a

    Scenario: A remote command executor that fails leaves the task unchanged
        Given a plugin command "/deploy" whose body is a JSON-RPC hook that answers 503
        When the reporter sends "/deploy prod"
        Then the reply is "/deploy failed: hook transport"
        And the task's state, settings and history are as before, and the model is not called
    """
    h = await with_builtins(Harness([scripted("Refunded.")]))
    down = httpx.MockTransport(lambda request: httpx.Response(503))
    loader = PluginLoader(
        hook_manager=h.hooks,
        registrar=RecordingRegistrar(),
        data_root=tmp_path,
        providers=Providers(http_client_factory=lambda: httpx.AsyncClient(transport=down)),
        commands=h.commands,
    )
    rpc = HookDef(
        name="deploy-rpc",
        url=HttpUrl("https://hooks.example/rpc"),
        points=("command.invoked.in",),
    )
    deploy = CommandDef(name="deploy", description="Deploy", hook="deploy-rpc")
    await loader.load(Plugin(manifest=MANIFEST, hooks=(rpc,), commands=(deploy,)))
    tq, tid = ids()
    async with h.worker(env.client, tq):
        handle = await send(
            env.client, tq, start(task(tid)), message("refund 48213", task_id=tid, message_id="m1")
        )
        before = await awaiting_next_message(handle)
        await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
            TaskWorkflow.inbox, message("/deploy prod", task_id=tid, message_id="m2")
        )
        after = await until(handle, replied("/deploy failed: hook transport"))
        assert after.state == before.state and after.sub_state is before.sub_state
        assert after.ext == before.ext
        await close(handle)
    assert len(h.llm.requests) == 1
