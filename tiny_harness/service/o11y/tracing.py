"""Trace export (R17.4, R17.5): an OTLP endpoint, Langfuse through its OTLP ingestion
endpoint, or an injected exporter for tests. Temporal and MCP propagate the context
with their own integrations; this module only decides where spans go."""

from __future__ import annotations

import base64

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

from tiny_harness.config import O11yConfig

LANGFUSE_PATH = "/api/public/otel/v1/traces"


def langfuse_headers(public_key: str, secret_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def configure_tracing(
    config: O11yConfig,
    *,
    service_name: str = "tiny-harness",
    exporter: SpanExporter | None = None,
    set_global: bool = True,
) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    if config.otlp_endpoint is not None:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=str(config.otlp_endpoint)))
        )
    if config.langfuse_public_key is not None and config.langfuse_secret_key is not None:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=str(config.langfuse_host).rstrip("/") + LANGFUSE_PATH,
                    headers=langfuse_headers(
                        config.langfuse_public_key.get_secret_value(),
                        config.langfuse_secret_key.get_secret_value(),
                    ),
                )
            )
        )
    if set_global:
        trace.set_tracer_provider(provider)
    return provider


__all__ = ["LANGFUSE_PATH", "configure_tracing", "langfuse_headers"]
