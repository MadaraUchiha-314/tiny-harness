"""Trace export (R17.4, R17.5): an OTLP endpoint, Langfuse through its OTLP ingestion
endpoint, or an injected exporter for tests. Temporal and MCP propagate the context
with their own integrations; this module only decides where spans go."""

from __future__ import annotations

import base64
import json
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from pathlib import Path

from opentelemetry import context, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)

from tiny_harness.config import O11yConfig

LANGFUSE_PATH = "/api/public/otel/v1/traces"


def langfuse_headers(public_key: str, secret_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class JsonLinesExporter(SpanExporter):
    """One JSON object per finished span, appended to a file: the trace evidence of the
    testing plan (T4, T12) without a collector. Attributes were redacted at creation."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self.path.open("a", encoding="utf-8") as handle:
            for span in spans:
                context = span.get_span_context()
                parent = span.parent
                record = {
                    "name": span.name,
                    "trace_id": f"{context.trace_id:032x}" if context else "",
                    "span_id": f"{context.span_id:016x}" if context else "",
                    "parent_id": f"{parent.span_id:016x}" if parent else "",
                    "start": span.start_time,
                    "end": span.end_time,
                    "status": span.status.status_code.name,
                    "attributes": dict(span.attributes or {}),
                }
                handle.write(json.dumps(record, default=str) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


NO_EXPORT = context.create_key("tiny_harness.no_export")
"""Set in the context while a span could record a secret no redactor knows, such as a
push token in an A2A SDK error (issue-27 abuse case 7)."""


@contextmanager
def no_export() -> Generator[None]:
    """Spans started inside this block, and their children, are never exported."""
    token = context.attach(context.set_value(NO_EXPORT, True))
    try:
        yield
    finally:
        context.detach(token)


class ExportGuard(SpanProcessor):
    """Forwards every span to ``inner`` except those started under ``no_export``."""

    def __init__(self, inner: SpanProcessor) -> None:
        self.inner = inner
        self._hidden: set[int] = set()

    def on_start(self, span: Span, parent_context: context.Context | None = None) -> None:
        parent = span.parent
        if context.get_value(NO_EXPORT, parent_context) or (
            parent is not None and parent.span_id in self._hidden
        ):
            if span.context is not None:
                self._hidden.add(span.context.span_id)
            return
        self.inner.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        span_id = span.context.span_id if span.context is not None else None
        if span_id in self._hidden:
            self._hidden.discard(span_id)
            return
        self.inner.on_end(span)

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)


def configure_tracing(
    config: O11yConfig,
    *,
    service_name: str = "tiny-harness",
    exporter: SpanExporter | None = None,
    set_global: bool = True,
) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        provider.add_span_processor(ExportGuard(SimpleSpanProcessor(exporter)))
    if config.trace_file is not None:
        provider.add_span_processor(
            ExportGuard(SimpleSpanProcessor(JsonLinesExporter(config.trace_file)))
        )
    if config.otlp_endpoint is not None:
        provider.add_span_processor(
            ExportGuard(BatchSpanProcessor(OTLPSpanExporter(endpoint=str(config.otlp_endpoint))))
        )
    if config.langfuse_public_key is not None and config.langfuse_secret_key is not None:
        langfuse = OTLPSpanExporter(
            endpoint=str(config.langfuse_host).rstrip("/") + LANGFUSE_PATH,
            headers=langfuse_headers(
                config.langfuse_public_key.get_secret_value(),
                config.langfuse_secret_key.get_secret_value(),
            ),
        )
        provider.add_span_processor(ExportGuard(BatchSpanProcessor(langfuse)))
    if set_global:
        trace.set_tracer_provider(provider)
    return provider


__all__ = [
    "LANGFUSE_PATH",
    "NO_EXPORT",
    "ExportGuard",
    "JsonLinesExporter",
    "configure_tracing",
    "langfuse_headers",
    "no_export",
]
