"""The hook-wrapped operation runner (R2.2-R2.4, R2.11, abuse case 6).

Every operation the harness performs runs through ``OperationRunner.run``: the ``pre``
chain may replace the input, the body runs, the ``post`` chain may replace the output.
The redactor scrubs the context before any executor sees it and the output before it is
returned, so neither a remote hook nor a recorded result ever carries a credential-shaped
string. The same wrapper is the body of every Temporal activity (Layer 5), which is why
hooks never run in workflow code.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from tiny_harness.harness.hooks.base import HookContext, HookManager, HookPoint, Operation, Phase
from tiny_harness.harness.security import Redactor


class OperationRunner:
    def __init__(self, hooks: HookManager, redactor: Redactor | None = None) -> None:
        self._hooks = hooks
        self._redactor = redactor or Redactor()

    @property
    def hooks(self) -> HookManager:
        return self._hooks

    @property
    def redactor(self) -> Redactor:
        return self._redactor

    async def run[Pre: HookContext, Post: HookContext, Out](
        self,
        operation: Operation,
        pre: Pre,
        body: Callable[[Pre], Awaitable[Out]],
        *,
        make_post: Callable[[Pre, Out], Post],
        extract: Callable[[Post], Out],
    ) -> Out:
        """``pre``, then the body, then ``post``; the replacement at each phase is what flows on."""
        pre_ctx = await self._hooks.run(
            HookPoint(operation=operation, phase=Phase.PRE), self._redactor.scrub(pre)
        )
        out = await body(pre_ctx)
        post_ctx = await self._hooks.run(
            HookPoint(operation=operation, phase=Phase.POST),
            self._redactor.scrub(make_post(pre_ctx, out)),
        )
        return extract(post_ctx)

    async def run_in[Ctx: HookContext](self, operation: Operation, ctx: Ctx) -> Ctx:
        """An ``in``-phase operation: the body is the chain itself (default at 1000)."""
        return await self._hooks.run(
            HookPoint(operation=operation, phase=Phase.IN), self._redactor.scrub(ctx)
        )


__all__ = ["OperationRunner"]
