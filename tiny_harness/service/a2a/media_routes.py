"""The media route ``GET /media/{task_id}/{media_id}`` (issue-38 R2.2, R4.2, R6.3, abuse
cases 4 and 6).

Any participant of a task fetches the task's media by one URL, from any surface:

1. the participant is resolved exactly as the A2A routes resolve it (the
   ``X-Participant-Id`` header, or the host's ``ParticipantResolver``), and the task must
   allow them (``AccessPolicy``); otherwise ``404``, never ``403``, so the ids of another
   task cannot be confirmed;
2. an id that is not ``[A-Za-z0-9_-]{1,128}``, or that names no media of that task, is
   ``404``;
3. the response is typed by the stored ref (an accepted raster image or audio type, or
   the PCM speech type), with ``nosniff``, an inline disposition with a sanitised name, and
   ``Content-Security-Policy: default-src 'none'``;
4. a closed object is served from its file; a growing one (a spoken reply being written)
   streams as it grows, ends cleanly when it is done, and is left incomplete (the
   connection breaks) when speech fails or a newer generation starts, so the surface marks
   it interrupted and may replay the URL.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import quote

from a2a.server.context import ServerCallContext
from a2a.types import Task
from starlette.requests import Request
from starlette.responses import FileResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from tiny_harness.harness.media import (
    PCM_MEDIA_TYPE,
    FileMediaStore,
    MediaFailed,
    MediaInterrupted,
    MediaRef,
    MediaStore,
)
from tiny_harness.harness.media.extension import MEDIA_ROUTE
from tiny_harness.service.a2a.task_store import AccessPolicy

log = logging.getLogger("tiny_harness.a2a.media")

MEDIA_PATH: Final = MEDIA_ROUTE + "/{task_id}/{media_id}"
_SAFE_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,128}")
_CLOSED_CACHE: Final = "private, max-age=3600"
_GROWING_CACHE: Final = "no-store"

TaskLookup = Callable[[str], Awaitable[Task | None]]
ContextOf = Callable[[Request], ServerCallContext]


@dataclass(frozen=True)
class MediaSource:
    """What the route serves from: the media store, and the task lookup the access policy
    is applied to (``TemporalTaskStore.lookup``: only this agent's tasks)."""

    store: MediaStore
    lookup: TaskLookup
    policy: AccessPolicy = field(default_factory=AccessPolicy)
    poll: float = 0.05
    idle_timeout: float = 30.0


def _ascii_name(name: str) -> str:
    return "".join(c if " " <= c <= "~" and c not in '"\\' else "_" for c in name)


def disposition(ref: MediaRef) -> str:
    """``inline`` with the ref's (already sanitised) name: an ASCII ``filename`` with
    quotes, backslashes and anything outside printable ASCII replaced, plus an RFC 5987
    ``filename*`` when the name is not plain ASCII."""
    name = ref.name or ref.id
    plain = _ascii_name(name)
    value = f'inline; filename="{plain}"'
    if plain != name:
        value += f"; filename*=UTF-8''{quote(name, safe='')}"
    return value


def media_headers(ref: MediaRef, *, growing: bool) -> dict[str, str]:
    return {
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": disposition(ref),
        "Cache-Control": _GROWING_CACHE if growing else _CLOSED_CACHE,
        "Content-Security-Policy": "default-src 'none'",
    }


def is_growing(ref: MediaRef) -> bool:
    """A spoken reply still being written: its ref gets its size when it is done."""
    return ref.media_type == PCM_MEDIA_TYPE and ref.size == 0


class GrowingMediaResponse(StreamingResponse):
    """A chunked body that is completed only when the object is done. When speech fails or
    is superseded the response is abandoned without its last body message, so the server
    closes the connection and the client sees a broken stream, not a short clean one."""

    def __init__(self, chunks: AsyncIterator[bytes], ref: MediaRef) -> None:
        headers = media_headers(ref, growing=True)
        super().__init__(chunks, media_type=ref.media_type, headers=headers)
        self._chunks = chunks
        self._ref = ref

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers}
        )
        try:
            async for chunk in self._chunks:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
        except (MediaFailed, MediaInterrupted) as exc:
            log.info(
                "media stream aborted",
                extra={"task_id": self._ref.task_id, "media_id": self._ref.id, "code": exc.code},
            )
            return
        finally:
            aclose = getattr(self._chunks, "aclose", None)
            if aclose is not None:
                await aclose()
        await send({"type": "http.response.body", "body": b"", "more_body": False})


async def media_response(source: MediaSource, ref: MediaRef) -> Response:
    """The response for a ref the store found. A file that retention removed after the
    lookup is ``404``: the file is looked at here, not first when the response is sent."""
    if is_growing(ref):
        chunks = source.store.read_stream(ref, poll=source.poll, idle_timeout=source.idle_timeout)
        return GrowingMediaResponse(chunks, ref)
    headers = media_headers(ref, growing=False)
    store = source.store
    if isinstance(store, FileMediaStore):
        path = store.root / ref.task_id / ref.id
        try:
            stat_result = await asyncio.to_thread(os.stat, path)
        except FileNotFoundError:
            return Response(status_code=404)
        return FileResponse(
            path, media_type=ref.media_type, headers=headers, stat_result=stat_result
        )
    stream = store.read_stream(ref, poll=source.poll, idle_timeout=source.idle_timeout)
    return StreamingResponse(stream, media_type=ref.media_type, headers=headers)


def media_route(source: Callable[[], MediaSource | None], context_of: ContextOf) -> Route:
    """The route; ``source`` is read per request (``None`` until the harness has started,
    or without media: ``404``), and ``context_of`` is the A2A routes' context builder."""

    async def media_view(request: Request) -> Response:
        media = source()
        task_id = str(request.path_params["task_id"])
        media_id = str(request.path_params["media_id"])
        if media is None or not (_SAFE_ID.fullmatch(task_id) and _SAFE_ID.fullmatch(media_id)):
            return Response(status_code=404)
        try:
            context = context_of(request)
        except Exception:  # the host's resolver failed; it is logged by the builder
            return Response(status_code=500)
        task = await media.lookup(task_id)
        if task is None or not media.policy.allows(task, context):
            return Response(status_code=404)
        ref = await media.store.lookup(task_id, media_id)
        if ref is None:
            return Response(status_code=404)
        return await media_response(media, ref)

    return Route(MEDIA_PATH, media_view, methods=["GET"])


__all__ = [
    "MEDIA_PATH",
    "GrowingMediaResponse",
    "MediaSource",
    "disposition",
    "is_growing",
    "media_headers",
    "media_response",
    "media_route",
]
