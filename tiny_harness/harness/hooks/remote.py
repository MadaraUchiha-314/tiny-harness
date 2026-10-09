"""Remote hook executors (R2.6): sherma's two transports, without its silent pass-through.

A remote executor sends the typed context as JSON and parses the reply back into the
same model. ``JsonRpcHookExecutor`` posts JSON-RPC 2.0 requests whose method is the hook
point (``llm.invoked.pre``) with ``{"context": ...}`` as params and expects
``{"context": ...}`` or ``null`` as the result. ``McpHookExecutor`` connects to an MCP
server and calls the tool named ``hooks.<operation>.<phase>`` with ``{"context": ...}``,
reading the context back from the tool's structured content (or its first text block).
Any transport failure, non-conforming reply or server-side error raises
``HookTransportError``: the operation fails through the normal retry path and
``activity.failed`` runs; nothing passes through silently (abuse case: a down policy
server must not mean "no policy").
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import cast

import httpx
from mcp import Client, StdioServerParameters
from mcp.client import Transport
from mcp.server import MCPServer
from mcp.types import TextContent

from tiny_harness.errors import AbortReason, HookAbort, HookTransportError
from tiny_harness.harness.hooks.base import HookContext, HookPoint
from tiny_harness.harness.hooks.providers import HttpClientFactory, default_http_client

JsonObject = dict[str, object]


def _parse_reply(
    executor: str, point: HookPoint, ctx: HookContext, payload: object
) -> HookContext | None:
    """Turn a reply into the context's type, ``None`` for an explicit pass-through."""
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise HookTransportError(
            "remote hook replied with something other than a context object",
            executor=executor,
            point=str(point),
        )
    reply = cast(JsonObject, payload)
    if reply.get("abort") is not None:
        abort = reply["abort"]
        reason = "refused"
        if isinstance(abort, dict):
            reason = str(cast(JsonObject, abort).get("reason", "refused"))
        try:
            parsed = AbortReason(reason)
        except ValueError as exc:
            raise HookTransportError(
                "remote hook aborted with an unknown reason", executor=executor, reason=reason
            ) from exc
        raise HookAbort(f"aborted by remote hook {executor}", reason=parsed)
    try:
        return type(ctx).model_validate(reply.get("context", reply))
    except ValueError as exc:
        raise HookTransportError(
            "remote hook reply does not parse as the context type",
            executor=executor,
            point=str(point),
            error=str(exc),
        ) from exc


class JsonRpcHookExecutor:
    """A hook executor behind a JSON-RPC 2.0 endpoint over HTTPS (R2.6)."""

    def __init__(
        self,
        name: str,
        url: str,
        *,
        priority: int = 500,
        points: Iterable[HookPoint] | None = None,
        http_client_factory: HttpClientFactory = default_http_client,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._name = name
        self._url = url
        self._priority = priority
        self._points = None if points is None else frozenset(points)
        self._http = http_client_factory
        self._headers = dict(headers or {})
        self._id = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def points(self) -> frozenset[HookPoint] | None:
        return self._points

    async def handle(self, point: HookPoint, ctx: HookContext) -> HookContext | None:
        self._id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": str(point),
            "params": {"context": ctx.model_dump(mode="json")},
        }
        try:
            async with self._http() as client:
                response = await client.post(self._url, json=request, headers=self._headers)
                response.raise_for_status()
                body = cast(object, response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise HookTransportError(
                "remote hook unreachable", executor=self._name, url=self._url, error=str(exc)
            ) from exc
        if not isinstance(body, dict):
            raise HookTransportError("malformed JSON-RPC reply", executor=self._name, url=self._url)
        reply = cast(JsonObject, body)
        if reply.get("error") is not None:
            raise HookTransportError(
                "remote hook returned a JSON-RPC error",
                executor=self._name,
                url=self._url,
                error=json.dumps(reply["error"]),
            )
        return _parse_reply(self._name, point, ctx, reply.get("result"))


class McpHookExecutor:
    """A hook executor behind an MCP server exposing ``hooks.<operation>.<phase>`` tools (R2.6)."""

    def __init__(
        self,
        name: str,
        server: MCPServer[object] | StdioServerParameters | Transport | str,
        *,
        priority: int = 500,
        points: Iterable[HookPoint] | None = None,
    ) -> None:
        self._name = name
        self._server = server
        self._priority = priority
        self._points = None if points is None else frozenset(points)

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def points(self) -> frozenset[HookPoint] | None:
        return self._points

    async def handle(self, point: HookPoint, ctx: HookContext) -> HookContext | None:
        tool = f"hooks.{point}"
        try:
            async with Client(self._server) as client:
                result = await client.call_tool(tool, {"context": ctx.model_dump(mode="json")})
        except Exception as exc:  # the MCP SDK raises transport-specific exceptions
            raise HookTransportError(
                "MCP hook server unreachable or tool call failed",
                executor=self._name,
                tool=tool,
                error=str(exc),
            ) from exc
        if result.is_error:
            texts = [c.text for c in result.content if isinstance(c, TextContent)]
            raise HookTransportError(
                "MCP hook tool reported an error",
                executor=self._name,
                tool=tool,
                error=" ".join(texts),
            )
        payload: object = result.structured_content
        if payload is None:
            texts = [c.text for c in result.content if isinstance(c, TextContent)]
            if not texts or texts[0].strip() in ("", "null"):
                return None
            try:
                payload = json.loads(texts[0])
            except ValueError as exc:
                raise HookTransportError(
                    "MCP hook tool replied with non-JSON text", executor=self._name, tool=tool
                ) from exc
        return _parse_reply(self._name, point, ctx, payload)


__all__ = ["JsonRpcHookExecutor", "McpHookExecutor"]
