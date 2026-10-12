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
