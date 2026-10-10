"""Validation against the vendored A2UI 0.9 schemas (R20.5).

The schema files reference each other by ``$id``; the registry holds every file under
its ``$id`` and under the relative name the message schema uses, so ``catalog.json``
resolves to the basic catalog.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Final, Literal, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from jsonschema.exceptions import (
    best_match as _best_match,  # pyright: ignore[reportUnknownVariableType]
)
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tiny_harness.errors import TinyHarnessError
from tiny_harness.jsontypes import JsonObject, JsonSchema

SCHEMAS: Final = Path(__file__).parent / "schemas"
SPEC_BASE: Final = "https://a2ui.org/specification/v0_9/"
type Direction = Literal["server_to_client", "client_to_server"]


class A2UIValidationError(TinyHarnessError):
    """An A2UI payload that does not validate against the 0.9 schemas."""

    code = "a2ui.invalid"


def _load(name: str) -> JsonSchema:
    return cast(JsonSchema, json.loads((SCHEMAS / name).read_text()))


@cache
def registry() -> Registry[JsonSchema]:
    files = (
        "common_types.json",
        "catalog.json",
        "server_to_client.json",
        "client_to_server.json",
        "client_capabilities.json",
        "client_data_model.json",
        "server_capabilities.json",
    )
    entries: list[tuple[str, Resource[JsonSchema]]] = []
    for name in files:
        schema = _load(name)
        resource = cast(Resource[JsonSchema], Resource(contents=schema, specification=DRAFT202012))
        entries.append((SPEC_BASE + name, resource))
        identifier = schema.get("$id")
        if isinstance(identifier, str):
            entries.append((identifier, resource))
    empty: Registry[JsonSchema] = Registry()
    return empty.with_resources(entries)


@cache
def validator(direction: Direction) -> Draft202012Validator:
    schema = _load(f"{direction}.json")
    if "$id" not in schema:
        schema = {**schema, "$id": SPEC_BASE + f"{direction}.json"}
    return Draft202012Validator(
        cast(dict[str, object], schema),
        registry=registry(),  # pyright: ignore[reportArgumentType]
    )


def validate_payload(payload: JsonObject, *, direction: Direction) -> None:
    """Raise ``A2UIValidationError`` naming the deepest failing path (the best match
    among a ``oneOf``'s branches), never the whole payload."""
    found = cast(
        Iterable[ValidationError],
        validator(direction).iter_errors(payload),  # pyright: ignore[reportUnknownMemberType]
    )
    errors: list[ValidationError] = list(found)
    if not errors:
        return
    exc = cast(ValidationError, _best_match(errors))  # pyright: ignore[reportUnknownArgumentType]
    path = "/" + "/".join(str(cast(object, p)) for p in exc.absolute_path)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    message = exc.message  # pyright: ignore[reportUnknownMemberType]
    raise A2UIValidationError(
        "A2UI payload failed validation", direction=direction, path=path, error=message[:300]
    ) from exc


__all__ = [
    "SCHEMAS",
    "SPEC_BASE",
    "A2UIValidationError",
    "registry",
    "validate_payload",
    "validator",
]
