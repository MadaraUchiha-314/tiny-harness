"""The o11y plugin's pure parts (R17.1, R17.2, R17.6)."""

from __future__ import annotations

import json
import logging

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tiny_harness.config import O11yConfig
from tiny_harness.harness.core.loop import (
    LLMInvokedPost,
    LLMInvokedPre,
    ToolInvokedPost,
    ToolInvokedPre,
)
from tiny_harness.harness.hooks import HookManager, Operation, OperationRunner
from tiny_harness.harness.models import LLMRequest, LLMResponse, scripted
from tiny_harness.harness.security import MASK, Redactor
from tiny_harness.harness.tools import ToolCall, ToolResult, WorkflowCommand
from tiny_harness.service.o11y import (
    JsonFormatter,
    O11yExecutor,
    configure_tracing,
    langfuse_headers,
)
from tiny_harness.service.o11y.hook import log as o11y_log


def test_log_record_shape_is_one_json_line_with_the_ids_and_phase() -> None:
    formatter = JsonFormatter(Redactor(secrets=["s3cr3t-value"]))
    record = logging.LogRecord(
        "tiny_harness.o11y",
        logging.INFO,
        __file__,
        1,
        "llm.invoked.pre token=s3cr3t-value",
        (),
        None,
    )
    record.fields = {  # type: ignore[attr-defined]
        "task_id": "t-1",
        "correlation_id": "c-1",
        "operation": "llm.invoked",
        "phase": "pre",
        "attempt": 1,
        "note": "Bearer abcdefghijklmnop",
    }
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO" and payload["logger"] == "tiny_harness.o11y"
    assert payload["task_id"] == "t-1" and payload["correlation_id"] == "c-1"
    assert payload["operation"] == "llm.invoked" and payload["phase"] == "pre"
    assert payload["msg"] == f"llm.invoked.pre token={MASK}"
    assert payload["note"] == MASK
    assert payload["ts"].endswith("+00:00")


async def test_one_span_per_operation_with_genai_attributes() -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracing(O11yConfig(), exporter=exporter, set_global=False)
    hooks = HookManager()
    executor = O11yExecutor(redactor=Redactor(secrets=["s3cr3t-value"]), provider=provider)
    hooks.register(executor)
    runner = OperationRunner(hooks)
    response: LLMResponse = scripted(
        "", tool_calls=[ToolCall(call_id="c1", name="orders.get_order", arguments={})]
    )

    async def llm(ctx: LLMInvokedPre) -> LLMResponse:
        return response

    out = await runner.run(
        Operation.LLM_INVOKED,
        LLMInvokedPre(
            task_id="t-1", correlation_id="c-1", request=LLMRequest(instructions="", input=())
        ),
        llm,
        make_post=lambda p, r: LLMInvokedPost(
            task_id=p.task_id, correlation_id=p.correlation_id, request=p.request, response=r
        ),
        extract=lambda post: post.response,
    )
    assert out.model == "fake-1"
    call = ToolCall(call_id="c1", name="orders.get_order", arguments={"token": "s3cr3t-value"})

    async def tool(ctx: ToolInvokedPre) -> ToolResult | WorkflowCommand:
        return ToolResult.error(ctx.call.call_id, "tool.failed", "nope")

    await runner.run(
        Operation.TOOL_INVOKED,
        ToolInvokedPre(task_id="t-1", correlation_id="c-1", call=call),
        tool,
        make_post=lambda p, r: ToolInvokedPost(
            task_id=p.task_id, correlation_id=p.correlation_id, call=p.call, result=r
        ),
        extract=lambda post: post.result,
    )
    spans = {s.name: s for s in exporter.get_finished_spans()}
    assert set(spans) == {"chat fake-1", "execute_tool orders.get_order"}
    chat = spans["chat fake-1"].attributes or {}
    assert chat["gen_ai.operation.name"] == "chat"
    assert chat["gen_ai.usage.input_tokens"] == 100 and chat["gen_ai.usage.output_tokens"] == 10
    assert chat["gen_ai.response.tool_calls"] == 1 and chat["tiny_harness.task_id"] == "t-1"
    tool_span = spans["execute_tool orders.get_order"]
    assert (tool_span.attributes or {})["gen_ai.tool.name"] == "orders.get_order"
    assert tool_span.status.status_code.name == "ERROR"
    assert executor.open_spans == 0


def test_langfuse_headers_are_basic_auth() -> None:
    headers = langfuse_headers("pk-lf-1", "sk-lf-2")
    assert headers == {"Authorization": "Basic cGstbGYtMTpzay1sZi0y"}
    assert o11y_log.name == "tiny_harness.o11y"
