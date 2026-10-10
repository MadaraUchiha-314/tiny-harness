"""Observability as a plugin on the hooks (R17): spans, structured logs, redaction."""

from tiny_harness.service.o11y.hook import O11yExecutor, span_name
from tiny_harness.service.o11y.logging import JsonFormatter, configure_logging
from tiny_harness.service.o11y.plugin import executor, o11y_plugin
from tiny_harness.service.o11y.tracing import configure_tracing, langfuse_headers

__all__ = [
    "JsonFormatter",
    "O11yExecutor",
    "configure_logging",
    "configure_tracing",
    "executor",
    "langfuse_headers",
    "o11y_plugin",
    "span_name",
]
