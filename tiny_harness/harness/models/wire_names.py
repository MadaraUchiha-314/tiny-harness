"""Provider-safe tool names (R18.1).

Registry tool names are ``<plugin>/<server>.<tool>``; OpenAI and Anthropic accept only
``[A-Za-z0-9_-]``. The mapping is built per request from the tools offered: every
disallowed character becomes ``_``, the name is cut to the providers' 64-character
limit and a collision (or a cut) gets a numeric suffix, so the wire name decodes back to
exactly one registry name. A call naming an unknown wire name
decodes to itself and the registry refuses it as an unknown tool.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from tiny_harness.harness.tools import ToolDefinition

_DISALLOWED = re.compile(r"[^A-Za-z0-9_-]")
MAX_WIRE_LENGTH = 64  # both providers' limit on a tool name
_BASE_LENGTH = MAX_WIRE_LENGTH - 8  # room for a collision suffix


def sanitize(name: str) -> str:
    """The provider-safe form of a name, cut to leave room for a collision suffix."""
    return (_DISALLOWED.sub("_", name) or "_")[:_BASE_LENGTH]


class WireNames:
    """A bijection between the request's registry tool names and provider-safe names."""

    def __init__(self, tools: Sequence[ToolDefinition] = ()) -> None:
        self._to_wire: dict[str, str] = {}
        self._to_registry: dict[str, str] = {}
        for tool in tools:
            self._add(tool.name)

    def _add(self, name: str) -> str:
        base = sanitize(name)
        wire, n = base, 1
        while wire in self._to_registry and self._to_registry[wire] != name:
            n += 1
            wire = f"{base}_{n}"
        self._to_wire[name] = wire
        self._to_registry[wire] = name
        return wire

    def encode(self, name: str) -> str:
        """The wire name for a registry name; a name not offered is sanitized ad hoc."""
        return self._to_wire.get(name) or self._add(name)

    def decode(self, wire: str) -> str:
        return self._to_registry.get(wire, wire)

    def description(self, tool: ToolDefinition) -> str:
        """The tool's description, naming the registry name when the wire name differs,
        so a skill or prompt that names the tool as the registry does still matches."""
        wire = self.encode(tool.name)
        if wire == tool.name:
            return tool.description
        return f"{tool.description} (registry name: {tool.name})"


__all__ = ["MAX_WIRE_LENGTH", "WireNames", "sanitize"]
