"""Hook executors the fixture plugin imports by path."""

from tiny_harness.harness.hooks import FunctionExecutor, HookContext, HookPoint


async def _audit(point: HookPoint, ctx: HookContext) -> HookContext | None:
    return None


audit = FunctionExecutor("audit", _audit, priority=100)
