"""An httpx transport that serves an ASGI app in-process and streams its response.

``httpx.ASGITransport`` collects a whole response body before returning it, so a
server-sent-event stream that stays open (``SubscribeToTask`` on a parked task) never
reaches the client. Over a real socket each event arrives as it is sent; this transport
does the same in-process, so a test sees what production sees: a response the app leaves
incomplete (it returns or fails before its last body message) breaks the client's read with
``httpx.RemoteProtocolError``, as a connection closed mid-body does."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
from starlette.types import ASGIApp, Message

_INCOMPLETE = "peer closed connection without sending complete message body"


class _Body(httpx.AsyncByteStream):
    def __init__(
        self, chunks: asyncio.Queue[bytes | Exception | None], app: asyncio.Task[None]
    ) -> None:
        self._chunks = chunks
        self._app = app

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while (chunk := await self._chunks.get()) is not None:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    async def aclose(self) -> None:
        # The client left: stop the app, as a closed socket would.
        if not self._app.done():
            self._app.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._app


class StreamingASGITransport(httpx.AsyncBaseTransport):
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(k.lower(), v) for k, v in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port or 80),
            "client": ("127.0.0.1", 123),
            "root_path": "",
        }
        sent = False
        started: asyncio.Future[tuple[int, list[tuple[bytes, bytes]]]] = (
            asyncio.get_running_loop().create_future()
        )
        chunks: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()
        complete = False

        async def receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()  # no disconnect until the app is cancelled
            return {"type": "http.disconnect"}  # pragma: no cover

        async def send(message: Message) -> None:
            nonlocal complete
            if message["type"] == "http.response.start":
                started.set_result((message["status"], list(message.get("headers", []))))
            elif message["type"] == "http.response.body":
                if chunk := message.get("body", b""):
                    await chunks.put(chunk)
                if not message.get("more_body", False):
                    complete = True
                    await chunks.put(None)

        async def run() -> None:
            try:
                await self.app(scope, receive, send)
            except Exception as exc:
                if not started.done():
                    started.set_exception(exc)
            finally:
                if not started.done():
                    started.set_result((500, []))
                if not complete:
                    await chunks.put(httpx.RemoteProtocolError(_INCOMPLETE))
                await chunks.put(None)

        app = asyncio.create_task(run())
        status, headers = await started
        return httpx.Response(status, headers=headers, stream=_Body(chunks, app), request=request)


__all__ = ["StreamingASGITransport"]
