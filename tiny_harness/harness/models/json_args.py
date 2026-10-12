"""Tool-call arguments from a model endpoint, parsed with a bounded nesting depth.

``json.loads`` only stops deep nesting by running out of recursion, and how deep that is
depends on the C stack: with an unlimited stack (``ulimit -s unlimited``, as on CI
runners) a 100 000-deep array parses, and rendering it into an error message then takes
minutes. The depth is checked first, so an over-deep body is a ``ValueError`` at once,
whatever the stack.
"""

from __future__ import annotations

import json
from typing import cast

MAX_DEPTH = 64
"""Deeper than any tool schema nests, and shallow enough that validating the parsed value
stays cheap; past it the body is refused unparsed."""


def nesting_depth(text: str) -> int:
    """The deepest ``[``/``{`` nesting in ``text``, ignoring brackets inside strings."""
    depth = deepest = 0
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif ch in "]}":
            depth -= 1
    return deepest


def loads_arguments(raw: str | None) -> object:
    """``json.loads`` of a tool call's arguments (``{}`` when empty), refusing a body
    nested deeper than ``MAX_DEPTH`` with a ``ValueError`` that does not echo it."""
    text = raw or "{}"
    if nesting_depth(text) > MAX_DEPTH:
        raise ValueError(f"tool-call arguments nest deeper than {MAX_DEPTH} levels")
    return cast(object, json.loads(text))


__all__ = ["MAX_DEPTH", "loads_arguments", "nesting_depth"]
