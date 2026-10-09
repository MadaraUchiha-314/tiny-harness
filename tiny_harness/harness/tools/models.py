"""Tool definitions, calls, results and the validating invoker (R6.3-R6.5, R6.7).

A tool is an entity with a ``ToolDefinition``; the LLM reaches it only by emitting a
``ToolCall`` whose name is in the registry and whose arguments validate against the
tool's input schema (abuse case 2). Every ``ToolResult`` is marked untrusted, so the
context window renders it as data. An intrinsic tool (decision-004) returns a
``WorkflowCommand`` instead of a result: the workflow applies it deterministically and
the LLM sees the command's ``result`` next turn.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from enum import StrEnum
from typing import Literal

import jsonschema
from pydantic import BaseModel, ConfigDict

from tiny_harness.errors import (
    EntityNotFoundError,
    ToolArgumentError,
    ToolNotFoundError,
    VersionNotFoundError,
)
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef, Registry
from tiny_harness.jsontypes import JsonObject, JsonSchema


class Idempotency(StrEnum):
    """Whether a failed call may be retried automatically (R6.7, R19.5)."""

    IDEMPOTENT = "idempotent"
    NOT_IDEMPOTENT = "not_idempotent"


class Execution(StrEnum):
    """Where the tool's body runs: an activity (MCP, remote) or an intrinsic command."""

    ACTIVITY = "activity"
    INTRINSIC = "intrinsic"


class ToolDefinition(BaseModel, frozen=True):
    """What the LLM sees and what the invoker validates against."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema | None = None
    idempotency: Idempotency = Idempotency.NOT_IDEMPOTENT
    execution: Execution = Execution.ACTIVITY


class ToolCall(BaseModel, frozen=True):
    """One call the LLM emitted; the only way text becomes an action."""

    call_id: str
    name: str
    arguments: JsonObject


class ContentPart(BaseModel, frozen=True):
    """A piece of a tool result: text, or JSON data with a media type."""

    kind: Literal["text", "data"]
    text: str | None = None
    data: JsonObject | None = None
    media_type: str | None = None


class ToolResult(BaseModel, frozen=True):
    """What goes back to the LLM. Always untrusted: data, never instructions (R6.5)."""

    call_id: str
    content: tuple[ContentPart, ...]
    is_error: bool = False
    untrusted: Literal[True] = True

    @classmethod
    def text(cls, call_id: str, text: str, *, is_error: bool = False) -> ToolResult:
        return cls(
            call_id=call_id, content=(ContentPart(kind="text", text=text),), is_error=is_error
        )

    @classmethod
    def error(cls, call_id: str, code: str, message: str) -> ToolResult:
        return cls.text(call_id, f"[{code}] {message}", is_error=True)


class WorkflowCommand(BaseModel, frozen=True):
    """An intrinsic's outcome: applied by the workflow with no I/O (design.md § Tools)."""

    kind: Literal[
        "attach_plan",
        "complete_step",
        "wait_for_reply",
        "spawn_subtask",
        "create_participant_task",
        "set_role",
        "skill_loaded",
        "skill_unloaded",
        "ui_emitted",
    ]
    call_id: str
    payload: JsonObject
    result: ToolResult


class Tool(Entity):
    """A tool entity. ``invoke`` runs the body; validation happens in the invoker."""

    kind = EntityKind.TOOL

    def __init__(self, ref: EntityRef, definition: ToolDefinition) -> None:
        super().__init__(ref)
        self.definition = definition

    @abstractmethod
    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand: ...


def validate_arguments(definition: ToolDefinition, call: ToolCall) -> None:
    """Raise ``ToolArgumentError`` when the call's arguments fail the input schema (R6.4)."""
    try:
        jsonschema.validate(call.arguments, definition.input_schema)
    except jsonschema.ValidationError as exc:
        raise ToolArgumentError(
            f"arguments do not match the schema of {definition.name}",
            validation=exc.message,
            tool=definition.name,
        ) from exc
    except jsonschema.SchemaError as exc:
        raise ToolArgumentError(
            f"tool {definition.name} has an invalid input schema",
            validation=str(exc),
            tool=definition.name,
        ) from exc


async def resolve_tool(registry: Registry, name: str) -> Tool:
    """The registered tool for a call's name, or ``ToolNotFoundError`` (R6.3)."""
    try:
        return await registry.get(EntityRef(kind=EntityKind.TOOL, id=name, version="*"), Tool)
    except (EntityNotFoundError, VersionNotFoundError) as exc:
        raise ToolNotFoundError("no such tool", tool=name) from exc


class ToolInvoker:
    """Validates then invokes: an unknown tool or invalid arguments become an error
    result for the LLM and nothing runs (R6.3, R6.4)."""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand:
        try:
            tool = await resolve_tool(self._registry, call.name)
        except ToolNotFoundError as exc:
            return ToolResult.error(call.call_id, exc.code, f"no such tool: {call.name}")
        try:
            validate_arguments(tool.definition, call)
        except ToolArgumentError as exc:
            return ToolResult.error(call.call_id, exc.code, exc.validation)
        return await tool.invoke(call)


def definition_json(definition: ToolDefinition) -> str:
    """The stable rendering the context window puts in the static prefix."""
    return json.dumps(definition.model_dump(mode="json"), sort_keys=True)


__all__ = [
    "ContentPart",
    "Execution",
    "Idempotency",
    "Tool",
    "ToolCall",
    "ToolDefinition",
    "ToolInvoker",
    "ToolResult",
    "WorkflowCommand",
    "definition_json",
    "resolve_tool",
    "validate_arguments",
]
