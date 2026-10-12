"""The built-in commands (R6.8, R7.2-7.4, R8.2-8.4, R9.1, R9.3, R10.1) and the built-in
role ``pre`` executor (abuse case 4): pure functions of the context and the catalog."""

from __future__ import annotations

import pytest

from tiny_harness.errors import HookAbort
from tiny_harness.harness.commands import (
    BUILTIN_SPECS,
    ChildSnapshot,
    CommandInvokedIn,
    CommandInvokedPre,
    CommandRegistry,
    CommandResult,
    SpawnIntent,
    TaskSettings,
    TaskSnapshot,
    effort_command,
    model_command,
    register_builtin_commands,
    register_role_policy,
    status_command,
    sub_task_command,
)
from tiny_harness.harness.core import Role, SubState
from tiny_harness.harness.hooks import (
    DEFAULT_BODY_PRIORITY,
    HookManager,
    HookPoint,
    Operation,
    Phase,
)
from tiny_harness.harness.models import ModelCatalog

CATALOG = ModelCatalog(default="model-a", selectable=("model-a", "model-b"))
PRE = HookPoint(operation=Operation.COMMAND_INVOKED, phase=Phase.PRE)
IN = HookPoint(operation=Operation.COMMAND_INVOKED, phase=Phase.IN)


def snapshot(**update: object) -> TaskSnapshot:
    return TaskSnapshot(id="t-1", name="Refund", state="INPUT_REQUIRED").model_copy(update=update)


def ctx(
    name: str,
    arguments: str = "",
    *,
    role: Role | None = Role.REPORTER,
    task: TaskSnapshot | None = None,
) -> CommandInvokedIn:
    return CommandInvokedIn(
        task_id="t-1",
        correlation_id="c-1",
        name=name,
        arguments=arguments,
        sender="alice",
        sender_role=role,
        task=task or snapshot(),
    )


def test_the_four_built_ins_are_declared() -> None:
    assert [s.name for s in BUILTIN_SPECS] == ["model", "effort", "sub-task", "status"]
    assert all(s.description for s in BUILTIN_SPECS)


# --- /model (R7) ----------------------------------------------------------------------


def test_model_without_an_argument_lists_the_current_and_the_selectable_models() -> None:
    out = model_command(ctx("model"), CATALOG)
    assert out.settings is None and out.spawn is None
    assert "model-a (default)" in out.reply and "model-a, model-b" in out.reply
    chosen = model_command(
        ctx("model", task=snapshot(settings=TaskSettings(model="model-b"))), CATALOG
    )
    assert "Model: model-b" in chosen.reply


def test_model_with_a_selectable_name_sets_it() -> None:
    out = model_command(ctx("model", "  model-b "), CATALOG)
    assert out.settings == TaskSettings(model="model-b")
    assert "model-b" in out.reply


@pytest.mark.parametrize(
    "name", ["evil-model", "MODEL-B", "model-b extra", "../../x", "model-\x1bb"]
)
def test_model_with_an_unlisted_name_is_refused_with_the_selectable_models(name: str) -> None:
    """Abuse cases 1 and 5: an exact allowlist compare; the hostile text is never echoed."""
    out = model_command(ctx("model", name), CATALOG)
    assert out.settings is None
    assert out.reply.startswith("refused:") and "model-a, model-b" in out.reply
    assert name.strip() not in out.reply


# --- /effort (R8) ---------------------------------------------------------------------


def test_effort_without_an_argument_reports_the_current_effort() -> None:
    assert "provider default" in effort_command(ctx("effort"), CATALOG).reply
    defaulted = CATALOG.model_copy(update={"default_effort": "low"})
    assert "Effort: low (default)" in effort_command(ctx("effort"), defaulted).reply
    chosen = snapshot(settings=TaskSettings(reasoning_effort="high"))
    out = effort_command(ctx("effort", task=chosen), CATALOG)
    assert "Effort: high" in out.reply and "low, medium, high" in out.reply


@pytest.mark.parametrize("value", ["low", "medium", "high"])
def test_effort_with_an_accepted_value_sets_it(value: str) -> None:
    out = effort_command(ctx("effort", value), CATALOG)
    assert out.settings == TaskSettings(reasoning_effort=value)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("value", ["extreme", "HIGH", "low; rm -rf ~"])
def test_effort_with_another_value_is_refused(value: str) -> None:
    """Abuse case 2: a closed set."""
    out = effort_command(ctx("effort", value), CATALOG)
    assert out.settings is None and out.reply.startswith("refused:")
    assert "low, medium, high" in out.reply


# --- /sub-task (R9) -------------------------------------------------------------------


def test_sub_task_asks_the_workflow_to_spawn_with_the_description_as_goal() -> None:
    out = sub_task_command(ctx("sub-task", " check the ledger $(rm -rf ~) "))
    assert out.spawn == SpawnIntent(goal="check the ledger $(rm -rf ~)")  # stored, never run
    assert out.settings is None


def test_sub_task_without_a_description_replies_with_the_usage() -> None:
    out = sub_task_command(ctx("sub-task", "   "))
    assert out.spawn is None and "/sub-task <description>" in out.reply


# --- /status (R10) --------------------------------------------------------------------


def test_status_reports_the_task_from_the_snapshot() -> None:
    task = snapshot(
        sub_state=SubState.AWAITING_NEXT_MESSAGE,
        settings=TaskSettings(reasoning_effort="low"),
        steps_done=2,
        steps_total=5,
        children=(ChildSnapshot(task_id="t-1.1", state="WORKING"),),
    )
    out = status_command(ctx("status", task=task), CATALOG)
    assert out == CommandResult(
        reply="\n".join(
            [
                "Task t-1 · Refund",
                "State: INPUT_REQUIRED · awaiting-next-message",
                "Model: model-a (default)",
                "Effort: low",
                "Plan: 2/5 steps done",
                "Sub-tasks:",
                "- t-1.1 · WORKING",
            ]
        )
    )


def test_status_of_a_bare_task() -> None:
    out = status_command(ctx("status"), CATALOG)
    assert out.reply.splitlines() == [
        "Task t-1 · Refund",
        "State: INPUT_REQUIRED",
        "Model: model-a (default)",
        "Effort: provider default",
        "Plan: none",
        "Sub-tasks: none",
    ]


# --- registration and the role policy -------------------------------------------------


async def test_the_built_ins_register_at_the_default_body_priority() -> None:
    hooks = HookManager()
    commands = CommandRegistry(hooks)
    register_builtin_commands(commands, CATALOG)
    assert commands.specs == BUILTIN_SPECS
    assert {e.priority for e in hooks.executors_for(IN)} == {DEFAULT_BODY_PRIORITY}
    out = await hooks.run(IN, ctx("model", "model-b"))
    assert out.result is not None and out.result.settings == TaskSettings(model="model-b")


def pre(name: str, arguments: str = "", role: Role | None = Role.WATCHER) -> CommandInvokedPre:
    return CommandInvokedPre.model_validate(
        ctx(name, arguments, role=role).model_dump(exclude={"result"})
    )


@pytest.mark.parametrize(
    ("name", "arguments"), [("model", "model-b"), ("effort", "low"), ("sub-task", "notes")]
)
async def test_the_role_policy_refuses_a_watchers_state_changing_command(
    name: str, arguments: str
) -> None:
    hooks = HookManager()
    register_role_policy(hooks)
    (executor,) = hooks.executors_for(PRE)
    assert executor.priority == 100
    with pytest.raises(HookAbort, match="watcher"):
        await hooks.run(PRE, pre(name, arguments))


@pytest.mark.parametrize(("name", "arguments"), [("model", ""), ("effort", " "), ("status", "")])
async def test_the_role_policy_lets_a_watcher_read(name: str, arguments: str) -> None:
    hooks = HookManager()
    register_role_policy(hooks)
    assert (await hooks.run(PRE, pre(name, arguments))).name == name


async def test_the_role_policy_refuses_any_command_from_a_sender_without_a_role() -> None:
    hooks = HookManager()
    register_role_policy(hooks)
    with pytest.raises(HookAbort, match="no role"):
        await hooks.run(PRE, pre("status", role=None))
    for role in (Role.REPORTER, Role.ASSIGNEE, Role.ADMIN):
        assert (await hooks.run(PRE, pre("model", "model-b", role=role))).arguments == "model-b"
