"""Tools (R6.3, R6.4, R6.5, R6.7): validation before invocation, untrusted results, commands."""

from __future__ import annotations

import pytest

from tiny_harness.harness.entities import EntityKind, EntityRef, Registry, RegistryEntry
from tiny_harness.harness.tools import (
    Execution,
    Idempotency,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolInvoker,
    ToolResult,
    WorkflowCommand,
    definition_json,
)
from tiny_harness.jsontypes import JsonSchema

ORDER_SCHEMA: JsonSchema = {
    "type": "object",
    "properties": {"order_id": {"type": "string"}},
    "required": ["order_id"],
    "additionalProperties": False,
}


class GetOrder(Tool):
    def __init__(self) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.TOOL, id="orders.get_order", version="1.0.0"),
            ToolDefinition(
                name="orders.get_order",
                description="Fetch an order",
                input_schema=ORDER_SCHEMA,
                idempotency=Idempotency.IDEMPOTENT,
            ),
        )
        self.calls: list[ToolCall] = []

    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand:
        self.calls.append(call)
        return ToolResult.text(call.call_id, f"order {call.arguments['order_id']} delivered")


class CreatePlan(Tool):
    def __init__(self) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.TOOL, id="create_plan", version=None),
            ToolDefinition(
                name="create_plan",
                description="Attach a plan",
                input_schema={"type": "object"},
                execution=Execution.INTRINSIC,
            ),
        )

    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand:
        return WorkflowCommand(
            kind="attach_plan",
            call_id=call.call_id,
            payload=call.arguments,
            result=ToolResult.text(call.call_id, "plan attached"),
        )


async def registry() -> tuple[Registry, GetOrder]:
    reg = Registry()
    tool = GetOrder()
    await reg.add(RegistryEntry(ref=tool.ref, instance=tool))
    plan = CreatePlan()
    await reg.add(RegistryEntry(ref=plan.ref, instance=plan))
    return reg, tool


async def test_valid_call_is_invoked_and_the_result_is_untrusted() -> None:
    reg, tool = await registry()
    result = await ToolInvoker(reg).invoke(
        ToolCall(call_id="c1", name="orders.get_order", arguments={"order_id": "48213"})
    )
    assert isinstance(result, ToolResult) and not result.is_error
    assert result.untrusted is True and result.content[0].text == "order 48213 delivered"
    assert len(tool.calls) == 1


async def test_unknown_tool_is_an_error_result_and_nothing_runs() -> None:
    reg, tool = await registry()
    result = await ToolInvoker(reg).invoke(ToolCall(call_id="c2", name="shell.exec", arguments={}))
    assert isinstance(result, ToolResult) and result.is_error
    assert "tool.not_found" in (result.content[0].text or "")
    assert tool.calls == []


async def test_invalid_arguments_are_an_error_result_and_nothing_runs() -> None:
    reg, tool = await registry()
    result = await ToolInvoker(reg).invoke(
        ToolCall(call_id="c3", name="orders.get_order", arguments={"order": "48213"})
    )
    assert isinstance(result, ToolResult) and result.is_error
    assert "tool.invalid_arguments" in (result.content[0].text or "")
    assert tool.calls == []


async def test_intrinsic_returns_a_workflow_command() -> None:
    reg, _ = await registry()
    out = await ToolInvoker(reg).invoke(
        ToolCall(call_id="c4", name="create_plan", arguments={"steps": []})
    )
    assert isinstance(out, WorkflowCommand) and out.kind == "attach_plan"
    assert out.result.call_id == "c4"


def test_definition_defaults_and_stable_rendering() -> None:
    definition = ToolDefinition(name="x", description="d", input_schema={"type": "object"})
    assert definition.idempotency is Idempotency.NOT_IDEMPOTENT
    assert definition.execution is Execution.ACTIVITY
    assert definition_json(definition) == definition_json(definition.model_copy())
    with pytest.raises(Exception):
        definition.name = "y"  # type: ignore[misc]
