"""Typed JSON aliases, so no ``dict[str, Any]`` appears anywhere (R22.2)."""

from __future__ import annotations

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]
type JsonSchema = dict[str, JsonValue]

__all__ = ["JsonObject", "JsonSchema", "JsonValue"]
