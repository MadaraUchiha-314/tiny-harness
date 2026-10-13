"""Temporal visibility queries built from values (issue-36 design § Security)."""

from __future__ import annotations


def visibility_literal(value: str) -> str:
    """``value`` as a quoted visibility-query string, backslashes and single quotes escaped.
    Only trusted values reach it (a configured task queue, a context id the caller checked);
    the escaping is defence in depth."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


__all__ = ["visibility_literal"]
