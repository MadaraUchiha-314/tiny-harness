"""Structured logging (R17.1): one JSON line per record, the same in every environment."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from tiny_harness.harness.security import Redactor

RECORD_FIELDS = ("task_id", "correlation_id", "operation", "phase", "attempt")


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
    *, level: int = logging.INFO, redactor: Redactor | None = None, name: str = "tiny_harness"
) -> logging.Logger:
    """Install the JSON formatter on the harness logger; idempotent."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    for handler in logger.handlers:
        if isinstance(handler.formatter, JsonFormatter):
            handler.formatter.redactor = redactor or handler.formatter.redactor
            return logger
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(redactor))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


__all__ = ["RECORD_FIELDS", "JsonFormatter", "configure_logging"]
