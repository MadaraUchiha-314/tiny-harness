"""Typed JSON aliases, so no ``dict[str, Any]`` appears anywhere (R22.2)."""

from __future__ import annotations

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
type JsonObject = dict[str, JsonValue]
type JsonSchema = dict[str, JsonValue]

__all__ = ["JsonObject", "JsonSchema", "JsonValue"]
