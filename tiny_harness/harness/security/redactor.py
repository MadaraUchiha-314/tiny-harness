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
import threading
from collections import Counter
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


def _plain(secrets: Iterable[str | SecretStr]) -> list[str]:
    return [s.get_secret_value() if isinstance(s, SecretStr) else s for s in secrets]


class SecretRegistry:
    """Every secret of every harness running in this process (issue-36 abuse case 6).

    A harness registers its secrets when it starts and removes them when it stops; a
    ``Redactor`` given the registry masks all of them, so one agent's logs never carry
    another agent's key. Values are counted, so two harnesses sharing one key keep it
    registered until both stop. ``version`` changes on every change."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Counter[str] = Counter()
        self.version = 0

    def register(self, secrets: Iterable[str | SecretStr]) -> None:
        with self._lock:
            self._values.update(_plain(secrets))
            self.version += 1

    def unregister(self, secrets: Iterable[str | SecretStr]) -> None:
        with self._lock:
            self._values.subtract(_plain(secrets))
            self._values = +self._values  # drop counts at zero
            self.version += 1

    def values(self) -> tuple[int, tuple[str, ...]]:
        with self._lock:
            return self.version, tuple(self._values)


PROCESS_SECRETS = SecretRegistry()
"""The process's one registry; the service's redactors read it."""


class Redactor:
    """Masks credential-shaped substrings and configured secret values in text and models.

    With a ``registry`` it also masks every secret registered there, re-reading it when
    its version changes."""

    def __init__(
        self, secrets: Iterable[str | SecretStr] = (), *, registry: SecretRegistry | None = None
    ) -> None:
        self._own = _plain(secrets)
        self._registry = registry
        self._version = -1
        self._sorted = self._sort(self._own)

    @staticmethod
    def _sort(values: Iterable[str]) -> list[str]:
        # Longest first, so a secret that contains another is masked whole.
        return sorted({v for v in values if len(v) >= 4}, key=len, reverse=True)

    @property
    def _values(self) -> list[str]:
        if self._registry is not None and self._registry.version != self._version:
            version, shared = self._registry.values()
            self._sorted = self._sort([*self._own, *shared])
            self._version = version
        return self._sorted

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


__all__ = ["MASK", "PROCESS_SECRETS", "Redactor", "SecretRegistry"]
