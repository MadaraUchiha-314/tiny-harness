"""MCP tool source (R6.1, R6.2, R6.6, abuse case 8): one MCP server's tools as entities.

``McpToolSource`` connects through the official ``mcp.Client`` (stdio through
``StdioServerParameters``, streamable HTTP through a URL, or an in-process server in
tests), lists the server's tools and wraps each as a ``McpTool`` named
``<server>.<tool>``. Idempotency comes from the server's own annotations
(``idempotent_hint`` or ``read_only_hint``), else not idempotent. Each tool's input
schema is hashed at registration; before the first invocation of any of the server's
tools in a loop iteration (``begin_iteration``) the source re-lists once and compares
the hashes, and a changed tool refuses every call with ``ToolSchemaChangedError`` until
it is re-registered. The client's outbound spans and ``traceparent`` propagation are the
SDK's own.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from typing import cast

from mcp import Client, StdioServerParameters
from mcp.client import Transport
from mcp.server import MCPServer
from mcp_types import CallToolResult, TextContent
from mcp_types import Tool as McpToolSpec

from tiny_harness.errors import RetryableProviderError, ToolSchemaChangedError
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.tools.models import (
    ContentPart,
    Idempotency,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolResult,
    WorkflowCommand,
)
from tiny_harness.jsontypes import JsonObject, JsonSchema, JsonValue

type ServerSpec = MCPServer[object] | StdioServerParameters | Transport | str
ServerFactory = Callable[[], ServerSpec]


def schema_hash(schema: JsonSchema) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()


def to_definition(server_name: str, spec: McpToolSpec) -> ToolDefinition:
    annotations = spec.annotations
    idempotent = bool(annotations and (annotations.idempotent_hint or annotations.read_only_hint))
    return ToolDefinition(
        name=f"{server_name}.{spec.name}",
        description=spec.description or spec.title or spec.name,
        input_schema=cast(JsonSchema, spec.input_schema),
        output_schema=cast(JsonSchema | None, spec.output_schema),
        idempotency=Idempotency.IDEMPOTENT if idempotent else Idempotency.NOT_IDEMPOTENT,
    )


def to_result(call_id: str, result: CallToolResult) -> ToolResult:
    parts: list[ContentPart] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(ContentPart(kind="text", text=block.text))
    structured = cast(object, result.structured_content)
    if isinstance(structured, dict):
        parts.append(
            ContentPart(
                kind="data", data=cast(JsonObject, structured), media_type="application/json"
            )
        )
    if not parts:
        parts.append(ContentPart(kind="text", text=""))
    return ToolResult(call_id=call_id, content=tuple(parts), is_error=result.is_error)


class McpTool(Tool):
    """One tool of one server; invoking it opens a session, calls, and maps the result."""

    def __init__(
        self, source: McpToolSource, spec_name: str, definition: ToolDefinition, version: str | None
    ) -> None:
        super().__init__(
            EntityRef(kind=EntityKind.TOOL, id=definition.name, version=version), definition
        )
        self._source = source
        self.spec_name = spec_name
        self.schema_hash = schema_hash(definition.input_schema)

    async def invoke(self, call: ToolCall) -> ToolResult | WorkflowCommand:
        await self._source.ensure_fresh()
        self._source.check_unchanged(self)
        try:
            async with Client(self._source.server()) as client:
                result = await client.call_tool(self.spec_name, dict(call.arguments))
        except Exception as exc:
            raise RetryableProviderError(
                f"MCP call failed: {exc}", provider=f"mcp:{self._source.name}", status=0
            ) from exc
        return to_result(call.call_id, result)


class McpToolSource:
    """One MCP server: its tools, their schema hashes, and the per-iteration drift check."""

    def __init__(
        self,
        name: str,
        server: ServerSpec | ServerFactory,
        *,
        version: str | None = None,
    ) -> None:
        self.name = name
        self._factory: ServerFactory = server if callable(server) else (lambda: server)
        self._version = version
        self._tools: dict[str, McpTool] = {}
        self._changed: set[str] = set()
        self._stale = False

    def server(self) -> ServerSpec:
        return self._factory()

    async def _list(self) -> Sequence[McpToolSpec]:
        async with Client(self.server()) as client:
            return (await client.list_tools()).tools

    async def tools(self) -> Sequence[McpTool]:
        """List the server's tools and (re)register them with fresh schema hashes (R6.2)."""
        specs = await self._list()
        self._tools = {
            spec.name: McpTool(self, spec.name, to_definition(self.name, spec), self._version)
            for spec in specs
        }
        self._changed.clear()
        self._stale = False
        return list(self._tools.values())

    def begin_iteration(self) -> None:
        """Mark the server as needing one re-list before its next invocation (abuse case 8)."""
        self._stale = True

    async def ensure_fresh(self) -> None:
        if not self._stale:
            return
        current = {
            spec.name: schema_hash(cast(JsonSchema, spec.input_schema))
            for spec in await self._list()
        }
        for spec_name, tool in self._tools.items():
            if current.get(spec_name) != tool.schema_hash:
                self._changed.add(spec_name)
        self._stale = False

    def check_unchanged(self, tool: McpTool) -> None:
        if tool.spec_name in self._changed:
            raise ToolSchemaChangedError(
                "tool schema changed since registration; re-register the server",
                tool=tool.definition.name,
                server=self.name,
            )

    @property
    def changed(self) -> frozenset[str]:
        return frozenset(self._changed)


def dump_schema(schema: JsonSchema) -> JsonValue:
    return cast(JsonValue, schema)


__all__ = [
    "McpTool",
    "McpToolSource",
    "ServerFactory",
    "ServerSpec",
    "schema_hash",
    "to_definition",
    "to_result",
]
