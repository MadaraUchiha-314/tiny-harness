"""Remote hook executors (R2.6): JSON-RPC and MCP transports, and the fail-closed rule."""

from __future__ import annotations

import json
from typing import cast

import httpx
import pytest
from mcp.server import MCPServer

from tiny_harness.errors import AbortReason, HookAbort, HookTransportError
from tiny_harness.harness.hooks import HookContext, HookManager, HookPoint, Operation, Phase
from tiny_harness.harness.hooks.remote import JsonRpcHookExecutor, McpHookExecutor


class Greeting(HookContext):
    text: str


POINT = HookPoint(operation=Operation.LLM_INVOKED, phase=Phase.PRE)


def ctx(text: str = "hello") -> Greeting:
    return Greeting(task_id="t1", correlation_id="c1", text=text)


def rpc_server(reply: object, *, status: int = 200) -> httpx.MockTransport:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = cast(dict[str, object], json.loads(request.content))
        seen.append(body)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": reply})

    transport = httpx.MockTransport(handler)
    transport.seen = seen  # type: ignore[attr-defined]
    return transport


def executor(transport: httpx.MockTransport) -> JsonRpcHookExecutor:
    return JsonRpcHookExecutor(
        "policy",
        "https://hooks.example/rpc",
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
    )


async def test_jsonrpc_sends_the_point_and_context_and_applies_the_reply() -> None:
    transport = rpc_server(
        {"context": {"task_id": "t1", "correlation_id": "c1", "text": "rewritten"}}
    )
    out = await executor(transport).handle(POINT, ctx())
    assert out is not None and isinstance(out, Greeting) and out.text == "rewritten"
    sent = transport.seen[0]  # type: ignore[attr-defined]
    assert sent["method"] == "llm.invoked.pre"
    assert sent["params"] == {
        "context": {"task_id": "t1", "correlation_id": "c1", "attempt": 1, "text": "hello"}
    }


async def test_jsonrpc_null_result_passes_through() -> None:
    assert await executor(rpc_server(None)).handle(POINT, ctx()) is None


async def test_jsonrpc_abort_reply_raises_hook_abort() -> None:
    with pytest.raises(HookAbort) as info:
        await executor(rpc_server({"abort": {"reason": "policy"}})).handle(POINT, ctx())
    assert info.value.reason is AbortReason.POLICY


async def test_unreachable_remote_hook_raises_and_never_passes_through() -> None:
    manager = HookManager()
    manager.register(executor(rpc_server(None, status=503)))
    with pytest.raises(HookTransportError, match="unreachable"):
        await manager.run(POINT, ctx())


async def test_jsonrpc_error_and_malformed_replies_fail_closed() -> None:
    with pytest.raises(HookTransportError, match="JSON-RPC error"):
        error = {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "boom"}}
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=error))
        await executor(transport).handle(POINT, ctx())
    with pytest.raises(HookTransportError, match="parse"):
        await executor(rpc_server({"context": {"text": 42}})).handle(POINT, ctx())


def hook_server(reply: object) -> MCPServer:
    server = MCPServer("hooks")

    @server.tool(name="hooks.llm.invoked.pre")
    def llm_invoked_pre(context: dict[str, object]) -> dict[str, object]:
        """Rewrite the greeting."""
        assert context["text"] == "hello"
        return cast(dict[str, object], reply)

    return server


async def test_mcp_executor_calls_the_tool_named_after_the_point() -> None:
    server = hook_server({"context": {"task_id": "t1", "correlation_id": "c1", "text": "from-mcp"}})
    out = await McpHookExecutor("mcp-policy", server).handle(POINT, ctx())
    assert out is not None and isinstance(out, Greeting) and out.text == "from-mcp"


async def test_mcp_executor_without_the_tool_fails_closed() -> None:
    server = MCPServer("empty")
    with pytest.raises(HookTransportError):
        await McpHookExecutor("mcp-policy", server).handle(POINT, ctx())
