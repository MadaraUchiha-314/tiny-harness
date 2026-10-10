"""The redactor (R17.6, abuse case 6): no credential-shaped string is ever recorded.

It runs at four points (design.md § Security design): over the inbound message before
update-with-start, over every activity argument and result at the workflow boundary,
over every persisted record, and over log fields and span attributes. It masks by shape
(bearer tokens, OpenAI ``sk-`` keys, Temporal ``tmprl`` keys, ``Authorization`` header
values, long base64-like blobs after a ``key``/``token``/``secret`` word) and by value
(every configured secret, whatever it looks like).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from typing import TypeVar, cast

from pydantic import BaseModel, SecretStr

MASK = "[REDACTED]"

_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\btmprl[A-Za-z0-9_-]{8,}"),
    re.compile(
        r"(?i)\b(authorization|x-api-key|api[_-]?key|secret|token|password)\b(\s*[:=]\s*)(\"?)([^\s\"',;]{8,})"
    ),
)

M = TypeVar("M", bound=BaseModel)


class Redactor:
    """Masks credential-shaped substrings and configured secret values in text and models."""

    def __init__(self, secrets: Iterable[str | SecretStr] = ()) -> None:
        values = [s.get_secret_value() if isinstance(s, SecretStr) else s for s in secrets]
        # Longest first, so a secret that contains another is masked whole.
        self._values = sorted((v for v in values if len(v) >= 4), key=len, reverse=True)

    def scrub_text(self, text: str) -> str:
        for value in self._values:
            text = text.replace(value, MASK)
        for pattern in _SHAPES:
            text = pattern.sub(self._mask_match, text)
        return text

    @staticmethod
    def _mask_match(match: re.Match[str]) -> str:
        if match.lastindex and match.lastindex >= 4:
            # keyword, separator, optional quote, value → keep the keyword, mask the value
            return f"{match.group(1)}{match.group(2)}{match.group(3)}{MASK}"
        return MASK

    def scrub_value(self, value: object) -> object:
        """Recursively scrub strings inside plain data (dicts, lists, tuples, models)."""
        if isinstance(value, Enum):
            return value  # a StrEnum is a str, but its value is a label, never a secret
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, SecretStr):
            return value
        if isinstance(value, BaseModel):
            return self.scrub(value)
        if isinstance(value, Mapping):
            mapping = cast(Mapping[object, object], value)
            scrubbed = {k: self.scrub_value(v) for k, v in mapping.items()}
            changed = any(scrubbed[k] is not v for k, v in mapping.items())
            return scrubbed if changed else mapping
        if isinstance(value, (tuple, list)):
            items = cast(Sequence[object], value)
            scrubbed_items = [self.scrub_value(v) for v in items]
            if all(a is b for a, b in zip(scrubbed_items, items, strict=True)):
                return items
            return tuple(scrubbed_items) if isinstance(value, tuple) else scrubbed_items
        return value

    def scrub(self, model: M) -> M:
        """A copy of the model with every string field scrubbed, nested models included."""
        updates: dict[str, object] = {}
        for name in type(model).model_fields:
            current = getattr(model, name)
            scrubbed = self.scrub_value(current)
            if scrubbed is not current:
                updates[name] = scrubbed
        return model.model_copy(update=updates) if updates else model


__all__ = ["MASK", "Redactor"]
