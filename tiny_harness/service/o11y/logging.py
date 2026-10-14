"""Structured logging (R17.1): one JSON line per record, the same in every environment."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import TextIO

from tiny_harness.harness.security import Redactor

RECORD_FIELDS = ("task_id", "correlation_id", "operation", "phase", "attempt")

CURRENT_AGENT: ContextVar[str | None] = ContextVar("tiny_harness_agent", default=None)
"""The agent whose request or activity this is (issue-36 NFR observability): set per request
by the harness's app and per activity by the worker's ``AgentContextInterceptor``, so five
agents in one process write tellable-apart log lines and spans."""


class JsonFormatter(logging.Formatter):
    """``{"ts", "level", "logger", "msg", ...fields}`` with every string redacted."""

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self.redactor = redactor or Redactor()

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": self.redactor.scrub_text(record.getMessage()),
        }
        agent = CURRENT_AGENT.get()
        if agent is not None:
            payload["agent"] = agent
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():  # type: ignore[misc]
                payload[str(key)] = (  # type: ignore[arg-type]
                    self.redactor.scrub_text(value) if isinstance(value, str) else value
                )
        if record.exc_info:
            payload["exception"] = self.redactor.scrub_text(self.formatException(record.exc_info))
        return json.dumps(payload, sort_keys=True, default=str)


def configure_logging(
    *,
    level: int = logging.INFO,
    redactor: Redactor | None = None,
    name: str = "tiny_harness",
    stream: TextIO | None = None,
) -> logging.Logger:
    """Install the JSON formatter on the harness logger; idempotent. ``stream`` defaults to
    stderr; the TUI hosting its own harness passes a log file so records never draw over
    the terminal it owns (issue-17)."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    for handler in logger.handlers:
        if isinstance(handler.formatter, JsonFormatter):
            handler.formatter.redactor = redactor or handler.formatter.redactor
            return logger
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(redactor))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


SDK_BODY_LOGGER = "a2a.server.routes.jsonrpc_dispatcher"


class DropRequestBodies(logging.Filter):
    """Drop the A2A SDK's DEBUG ``Request body: ...`` record: a body can carry a push
    config's token (issue-27 abuse case 7), and the record is outside the redactor's reach."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (isinstance(record.msg, str) and record.msg.startswith("Request body"))


def drop_sdk_request_bodies() -> None:
    """Install ``DropRequestBodies`` on the SDK's dispatcher logger; idempotent."""
    logger = logging.getLogger(SDK_BODY_LOGGER)
    if not any(isinstance(f, DropRequestBodies) for f in logger.filters):
        logger.addFilter(DropRequestBodies())


__all__ = [
    "CURRENT_AGENT",
    "RECORD_FIELDS",
    "SDK_BODY_LOGGER",
    "DropRequestBodies",
    "JsonFormatter",
    "configure_logging",
    "drop_sdk_request_bodies",
]
