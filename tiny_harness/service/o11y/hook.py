"""The observability hook executor (R17.1-R17.3, R17.6): one executor on every ``pre``
and ``post`` point. ``pre`` opens a span and makes it current, so provider and MCP
spans nest under it; ``post`` closes it with the GenAI semantic-convention attributes;
both write one structured log record. ``activity.failed`` records the failure on the
open span. Every attribute and log field passes through the redactor first.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, TracerProvider

from tiny_harness.harness.core.loop import (
    LLMInvokedPost,
    LLMInvokedPre,
    RequestReceivedPre,
    ToolInvokedPost,
    ToolInvokedPre,
)
from tiny_harness.harness.hooks import HookContext, HookPoint, Operation, Phase
from tiny_harness.harness.security import Redactor
from tiny_harness.harness.tools import ToolResult
from tiny_harness.service.durable.models import ActivityFailedPre, ActivityRetriedPre

log = logging.getLogger("tiny_harness.o11y")
AGENT_NAME = "tiny-harness"
TRACER = "tiny_harness"
PRE_ONLY = frozenset({Operation.TOOL_CALLS_EXTRACTED})
"""Points with a ``pre`` chain but no body or ``post``: logged, never spanned."""

type SpanKey = tuple[str, str, str, int]
type Attributes = dict[str, str | int | float | bool]


def span_name(point: HookPoint, ctx: HookContext, *, model: str | None = None) -> str:
    """GenAI span names: ``chat {model}``, ``execute_tool {tool}``, ``invoke_agent {agent}``,
    ``plan``; every other operation is named after itself."""
    operation = point.operation
    if operation is Operation.LLM_INVOKED:
        return f"chat {model}" if model else "chat"
    if operation is Operation.TOOL_INVOKED and isinstance(ctx, ToolInvokedPre):
        return f"execute_tool {ctx.call.name}"
    if operation is Operation.REQUEST_RECEIVED:
        return f"invoke_agent {AGENT_NAME}"
    if operation is Operation.PLAN_CREATED:
        return "plan"
    return operation.value


def _key(point: HookPoint, ctx: HookContext) -> SpanKey:
    return (ctx.task_id, ctx.correlation_id, point.operation.value, ctx.attempt)


class O11yExecutor:
    """Subscribes to every point; spans live from ``pre`` to ``post`` of one attempt."""

    def __init__(
        self,
        *,
        redactor: Redactor | None = None,
        priority: int = 0,
        provider: TracerProvider | None = None,
    ) -> None:
        self.redactor = redactor or Redactor()
        self.provider = provider
        self._priority = priority
        self._open: dict[SpanKey, tuple[Span, object]] = {}

    @property
    def name(self) -> str:
        return "o11y"

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def points(self) -> frozenset[HookPoint] | None:
        return None

    @property
    def open_spans(self) -> int:
        """Spans opened by ``pre`` and not yet closed; zero once every operation ended."""
        return len(self._open)

    async def handle(self, point: HookPoint, ctx: HookContext) -> HookContext | None:
        fields = self._fields(point, ctx)
        if point.phase is Phase.PRE and point.operation in (
            Operation.ACTIVITY_FAILED,
            Operation.ACTIVITY_RETRIED,
        ):
            self._record_failure(point, ctx, fields)
        elif point.phase is Phase.PRE and point.operation not in PRE_ONLY:
            self._open_span(point, ctx, fields)
        elif point.phase is Phase.POST:
            self._close_span(point, ctx, fields)
        log.info("%s", str(point), extra={"fields": fields})
        return None

    # --- spans -------------------------------------------------------------------------

    def _open_span(self, point: HookPoint, ctx: HookContext, fields: Attributes) -> None:
        provider = self.provider or trace.get_tracer_provider()
        tracer = provider.get_tracer(TRACER)
        attributes: Attributes = {
            "tiny_harness.task_id": ctx.task_id,
            "tiny_harness.correlation_id": ctx.correlation_id,
            "tiny_harness.operation": point.operation.value,
            "tiny_harness.attempt": ctx.attempt,
        }
        kind = SpanKind.INTERNAL
        if isinstance(ctx, LLMInvokedPre):
            attributes["gen_ai.operation.name"] = "chat"
            attributes["gen_ai.provider.name"] = "tiny_harness"
            attributes["gen_ai.request.tools"] = len(ctx.request.tools)
            kind = SpanKind.CLIENT
        elif isinstance(ctx, ToolInvokedPre):
            attributes["gen_ai.operation.name"] = "execute_tool"
            attributes["gen_ai.tool.name"] = ctx.call.name
            attributes["gen_ai.tool.call.id"] = ctx.call.call_id
        elif isinstance(ctx, RequestReceivedPre):
            attributes["gen_ai.operation.name"] = "invoke_agent"
            attributes["gen_ai.agent.name"] = AGENT_NAME
        elif point.operation is Operation.PLAN_CREATED:
            attributes["gen_ai.operation.name"] = "plan"
        span = tracer.start_span(
            span_name(point, ctx), kind=kind, attributes=self._scrub(attributes)
        )
        token = otel_context.attach(trace.set_span_in_context(span))
        self._open[_key(point, ctx)] = (span, token)

    def _close_span(self, point: HookPoint, ctx: HookContext, fields: Attributes) -> None:
        entry = self._open.pop(_key(point, ctx), None)
        if entry is None:
            return
        span, token = entry
        attributes: Attributes = {}
        if isinstance(ctx, LLMInvokedPost):
            response = ctx.response
            span.update_name(span_name(point, ctx, model=response.model))
            attributes["gen_ai.request.model"] = response.model
            attributes["gen_ai.response.model"] = response.model
            attributes["gen_ai.usage.input_tokens"] = response.usage.input_tokens
            attributes["gen_ai.usage.output_tokens"] = response.usage.output_tokens
            attributes["gen_ai.usage.cache_read.input_tokens"] = response.usage.cached_tokens
            attributes["gen_ai.response.finish_reasons"] = response.finish.value
            attributes["gen_ai.response.tool_calls"] = len(response.tool_calls)
        elif isinstance(ctx, ToolInvokedPost):
            result = ctx.result
            if isinstance(result, ToolResult):
                attributes["tiny_harness.tool.is_error"] = result.is_error
                if result.is_error:
                    span.set_status(Status(StatusCode.ERROR, "tool returned an error result"))
            else:
                attributes["tiny_harness.tool.command"] = result.kind
        span.set_attributes(self._scrub(attributes))
        otel_context.detach(token)  # type: ignore[arg-type]
        span.end()

    def _record_failure(self, point: HookPoint, ctx: HookContext, fields: Attributes) -> None:
        if isinstance(ctx, ActivityFailedPre):
            fields["activity"] = ctx.activity
            fields["error.type"] = ctx.error.type
            fields["error.message"] = self.redactor.scrub_text(ctx.error.message)
            key = (ctx.task_id, ctx.correlation_id, ctx.activity, ctx.attempt)
            entry = self._open.pop(key, None)
            if entry is not None:
                span, token = entry
                span.set_status(Status(StatusCode.ERROR, fields["error.message"]))
                otel_context.detach(token)  # type: ignore[arg-type]
                span.end()
            log.warning("activity failed: %s", ctx.activity, extra={"fields": dict(fields)})
        elif isinstance(ctx, ActivityRetriedPre):
            fields["activity"] = ctx.activity
            fields["next_delay_seconds"] = ctx.next_delay.total_seconds()

    # --- logging -----------------------------------------------------------------------

    def _fields(self, point: HookPoint, ctx: HookContext) -> Attributes:
        return {
            "task_id": ctx.task_id,
            "correlation_id": ctx.correlation_id,
            "operation": point.operation.value,
            "phase": point.phase.value,
            "attempt": ctx.attempt,
        }

    def _scrub(self, attributes: Mapping[str, str | int | float | bool]) -> Attributes:
        return {
            k: self.redactor.scrub_text(v) if isinstance(v, str) else v
            for k, v in attributes.items()
        }


__all__ = ["AGENT_NAME", "TRACER", "O11yExecutor", "log", "span_name"]
