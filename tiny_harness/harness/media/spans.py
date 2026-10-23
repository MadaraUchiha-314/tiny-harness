"""Media spans (issue-38 NFR observability): ``transcribe {model}``, ``speech {model}``
and ``image {model}`` like the ``chat`` span, and ``media.intake`` on the executor.

A span carries the model, the endpoint's host and port, the task and media ids, and
sizes (bytes, characters, duration): never bytes, base64, a prompt or a transcript
(abuse case 8). Each also writes one log line with the same fields when it ends. The
spans go to the process's tracer provider (the o11y plugin's), or the one ``tracing``
sets, as the o11y hook's do.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Final, Literal
from urllib.parse import urlsplit

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, TracerProvider

log = logging.getLogger("tiny_harness.o11y.media")
TRACER: Final = "tiny_harness"
MediaOperation = Literal["transcription", "speech", "image_generation"]
SPAN_NAMES: Final[dict[str, str]] = {
    "transcription": "transcribe",
    "speech": "speech",
    "image_generation": "image",
}
type Value = str | int | float | bool

_provider: TracerProvider | None = None


@contextmanager
def tracing(provider: TracerProvider | None) -> Generator[None]:
    """Send media spans to ``provider`` inside the block (tests; a host with its own)."""
    global _provider
    previous, _provider = _provider, provider
    try:
        yield
    finally:
        _provider = previous


def _tracer() -> trace.Tracer:
    return (_provider or trace.get_tracer_provider()).get_tracer(TRACER)


def endpoint_attributes(endpoint: str | None) -> dict[str, Value]:
    """OTel's client ``server.address`` and ``server.port`` of an endpoint's origin."""
    if endpoint is None:
        return {}
    parts = urlsplit(endpoint)
    attributes: dict[str, Value] = {}
    if parts.hostname:
        attributes["server.address"] = parts.hostname
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    if port is not None:
        attributes["server.port"] = port
    return attributes


class MediaSpan:
    """The open span: ``set`` records sizes and ids as they become known."""

    def __init__(self, span: Span, fields: dict[str, Value]) -> None:
        self._span = span
        self.fields = fields

    def set(self, **values: Value | None) -> None:
        """``tiny_harness.media.<key>`` for each value that is not ``None``."""
        for key, value in values.items():
            if value is None:
                continue
            name = key if "." in key else f"tiny_harness.media.{key}"
            self._span.set_attribute(name, value)
            self.fields[name] = value


@contextmanager
def _span(name: str, kind: SpanKind, attributes: dict[str, Value]) -> Generator[MediaSpan]:
    span = _tracer().start_span(name, kind=kind, attributes=attributes)
    media = MediaSpan(span, dict(attributes))
    try:
        with trace.use_span(
            span, end_on_exit=False, record_exception=False, set_status_on_exception=False
        ):
            yield media
    except BaseException as exc:
        media.set(**{"error.type": type(exc).__name__})
        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
        raise
    finally:
        span.end()
        log.info("%s", name, extra={"fields": media.fields})


@contextmanager
def media_span(
    operation: MediaOperation,
    *,
    provider: str,
    model: str,
    endpoint: str | None,
    task_id: str,
    media_id: str | None = None,
) -> Generator[MediaSpan]:
    """A provider call for media: ``<transcribe|speech|image> {model}``, a client span."""
    attributes: dict[str, Value] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model,
        "tiny_harness.task_id": task_id,
        **endpoint_attributes(endpoint),
    }
    if media_id is not None:
        attributes["tiny_harness.media.id"] = media_id
    with _span(f"{SPAN_NAMES[operation]} {model}", SpanKind.CLIENT, attributes) as span:
        yield span


@contextmanager
def intake_span(task_id: str, *, count: int, size: int) -> Generator[MediaSpan]:
    """``media.intake``: the files of one message, checked and stored; a refusal sets
    ``rejection`` (the check that refused it) before the error ends the span."""
    attributes: dict[str, Value] = {
        "tiny_harness.task_id": task_id,
        "tiny_harness.media.count": count,
        "tiny_harness.media.bytes": size,
    }
    with _span("media.intake", SpanKind.INTERNAL, attributes) as span:
        yield span


__all__ = [
    "SPAN_NAMES",
    "MediaOperation",
    "MediaSpan",
    "endpoint_attributes",
    "intake_span",
    "media_span",
    "tracing",
]
