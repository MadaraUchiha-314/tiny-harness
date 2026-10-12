"""Hook executors the fixture plugin imports by path."""

from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookPoint


async def _audit(point: HookPoint, ctx: HookContext) -> HookContext | None:
    return None


audit = FunctionExecutor("audit", _audit, priority=100)


async def _deploy(point: HookPoint, ctx: HookContext) -> HookContext | None:
    """A command body: answers whatever ``command.invoked.in`` context reaches it."""
    from tiny_harness.harness.commands import CommandInvokedIn, CommandResult

    assert isinstance(ctx, CommandInvokedIn)
    return ctx.model_copy(update={"result": CommandResult(reply=f"deployed {ctx.arguments}")})


deploy = FunctionExecutor("deploy", _deploy)


async def _status(point: HookPoint, ctx: HookContext) -> HookContext | None:
    """A plugin's replacement for the built-in ``/status`` body."""
    from tiny_harness.harness.commands import CommandInvokedIn, CommandResult

    assert isinstance(ctx, CommandInvokedIn)
    return ctx.model_copy(update={"result": CommandResult(reply=f"plugin status: {ctx.task.id}")})


status = FunctionExecutor("status", _status)


async def _no_sub_tasks(point: HookPoint, ctx: HookContext) -> HookContext | None:
    """An ordinary ``command.invoked.pre`` policy hook: it sees every command."""
    from tiny_harness.errors import AbortReason, HookAbort
    from tiny_harness.harness.commands import CommandInvokedPre

    if isinstance(ctx, CommandInvokedPre) and ctx.name == "sub-task":
        raise HookAbort("sub-tasks are disabled here", reason=AbortReason.POLICY)
    return None


no_sub_tasks = FunctionExecutor("no-sub-tasks", _no_sub_tasks)
