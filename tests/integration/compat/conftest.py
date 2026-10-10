"""A scripted OpenAI-compatible server on loopback (issue-19), and Settings that point the
real OpenAI adapter at it: embedded Temporal, no Temporal credentials, no OpenAI key."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest_asyncio
import uvicorn
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from tests.integration.durable.conftest import CACHE
from tests.integration.embedded.conftest import free_port
from tiny_harness.config import Settings

type Json = dict[str, object]


def responses_body(text: str) -> Json:
    """A completed Responses API body carrying one assistant message."""
    return {
        "id": "resp_compat",
        "object": "response",
        "created_at": 1760000000,
        "status": "completed",
        "model": "compat-model",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "metadata": {},
        "parallel_tool_calls": True,
        "temperature": 1.0,
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "output": [
            {
                "id": "msg_compat",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 50,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 55,
        },
    }


def chat_body(text: str) -> Json:
    """A Chat Completions body carrying one assistant message, without usage (R3.4)."""
    return {
        "id": "chatcmpl-compat",
        "object": "chat.completion",
        "created": 1760000000,
        "model": "compat-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }


@dataclass
class Seen:
    path: str
    headers: dict[str, str]
    body: Json


@dataclass
class CompatServer:
    """Answers each model call with the next scripted ``(status, body)``; the last one
    repeats. Every request is recorded."""

    url: str
    script: list[tuple[int, Json]] = field(default_factory=lambda: list[tuple[int, Json]]())
    seen: list[Seen] = field(default_factory=lambda: list[Seen]())

    def answer(self, *replies: tuple[int, Json]) -> None:
        self.script[:] = replies

    async def handle(self, request: Request) -> Response:
        body = json.loads(await request.body())
        self.seen.append(Seen(request.url.path, dict(request.headers), body))
        status, reply = self.script[0] if len(self.script) == 1 else self.script.pop(0)
        return JSONResponse(reply, status_code=status)


@pytest_asyncio.fixture
async def compat_server() -> AsyncIterator[CompatServer]:
    port = free_port()
    server = CompatServer(url=f"http://127.0.0.1:{port}/v1")
    app = Starlette(
        routes=[
            Route("/v1/responses", server.handle, methods=["POST"]),
            Route("/v1/chat/completions", server.handle, methods=["POST"]),
        ]
    )
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(uv.serve())
    while not uv.started:
        await asyncio.sleep(0.01)
    try:
        yield server
    finally:
        uv.should_exit = True
        await task


def compat_settings(tmp_path: Path, *, base_url: str, api: str) -> Settings:
    """Embedded Temporal and the real adapter at ``base_url``, with no OpenAI key."""
    port = free_port()
    return Settings.model_validate(
        {
            "temporal": {
                "mode": "embedded",
                "task_queue": f"compat-{uuid.uuid4().hex[:8]}",
                "embedded": {"download_dir": str(CACHE)},
            },
            "openai": {"base_url": base_url, "api": api, "model": "compat-model"},
            "server": {
                "bind": f"127.0.0.1:{port}",
                "base_url": f"http://127.0.0.1:{port}",
                "bridge_interval": "PT0.05S",
            },
            "retries": {"default": {"initial_interval": "PT0.2S", "maximum_attempts": 3}},
            "store": {"sqlite_path": str(tmp_path / "state" / "tiny-harness.sqlite3")},
            "push_key": SecretStr(base64.b64encode(os.urandom(32)).decode()),
        }
    )


__all__ = ["CompatServer", "chat_body", "compat_server", "compat_settings", "responses_body"]
