"""The two helpers the A2A SDK's protobuf types need inside the harness (design.md § Agents).

``ProtoJson[M]`` lets a Pydantic model hold a protobuf message as a field: it validates
from ProtoJSON (``ParseDict``) and serialises back (``MessageToDict``), so a workflow
payload or a stored record can carry an ``a2a.types.Task`` or ``Message`` unchanged.
``participant_of`` reads the asserted participant id from ``Message.metadata`` (the
self-asserted identity of decision-003).
"""

from __future__ import annotations

from typing import Annotated, cast

from a2a.types import Message
from google.protobuf import json_format
from google.protobuf import message as protobuf
from pydantic import PlainSerializer, PlainValidator, WithJsonSchema

from tiny_harness.jsontypes import JsonObject

PARTICIPANT_KEY = "participant_id"


def _serialise(value: protobuf.Message) -> JsonObject:
    return cast(JsonObject, json_format.MessageToDict(value, preserving_proto_field_name=False))


def proto_json[M: protobuf.Message](message_type: type[M]) -> object:
    """The ``Annotated`` metadata for a field of protobuf type ``message_type``."""

    def validate(value: object) -> M:
        if isinstance(value, message_type):
            return value
        if isinstance(value, dict):
            return json_format.ParseDict(cast(JsonObject, value), message_type())
        raise TypeError(
            f"expected {message_type.__name__} or its ProtoJSON, got {type(value).__name__}"
        )

    return (
        PlainValidator(validate),
        PlainSerializer(_serialise),
        WithJsonSchema(
            {"type": "object", "description": f"ProtoJSON of a2a.v1.{message_type.__name__}"}
        ),
    )


type ProtoJson[M: protobuf.Message] = Annotated[M, "proto-json"]
"""Use as ``Annotated[Task, *proto_json(Task)]``; the alias documents the intent."""


def participant_of(message: Message) -> str | None:
    """The asserted participant id, or ``None`` when the message carries none."""
    if not message.HasField("metadata"):
        return None
    fields = message.metadata.fields
    if PARTICIPANT_KEY not in fields:
        return None
    value = fields[PARTICIPANT_KEY]
    return value.string_value if value.HasField("string_value") and value.string_value else None


__all__ = ["PARTICIPANT_KEY", "ProtoJson", "participant_of", "proto_json"]
