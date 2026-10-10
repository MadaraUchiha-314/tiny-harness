"""Typed A2UI messages (R20.5): the four server messages and the two client messages,
each validated against the vendored schema before it is trusted."""

from __future__ import annotations

from typing import Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tiny_harness.interaction.a2ui.validation import A2UIValidationError, validate_payload
from tiny_harness.jsontypes import JsonObject, JsonValue

A2UI_VERSION: Final = "v0.9.1"
A2UI_EXT_URI: Final = "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
A2UI_MEDIA_TYPE: Final = "application/a2ui+json"
BASIC_CATALOG_ID: Final = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"


class _Message(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class CreateSurface(_Message):
    kind: Literal["createSurface"] = "createSurface"
    surface_id: str = Field(alias="surfaceId", min_length=1)
    catalog_id: str = Field(alias="catalogId", default=BASIC_CATALOG_ID)
    theme: JsonObject | None = None
    send_data_model: bool = Field(alias="sendDataModel", default=False)

    def payload(self) -> JsonObject:
        body: JsonObject = {"surfaceId": self.surface_id, "catalogId": self.catalog_id}
        if self.theme is not None:
            body["theme"] = self.theme
        if self.send_data_model:
            body["sendDataModel"] = True
        return {"version": A2UI_VERSION, "createSurface": body}


class UpdateComponents(_Message):
    kind: Literal["updateComponents"] = "updateComponents"
    surface_id: str = Field(alias="surfaceId", min_length=1)
    components: tuple[JsonObject, ...] = Field(min_length=1)

    def component_ids(self) -> tuple[str, ...]:
        return tuple(str(c["id"]) for c in self.components if "id" in c)

    def payload(self) -> JsonObject:
        return {
            "version": A2UI_VERSION,
            "updateComponents": {"surfaceId": self.surface_id, "components": list(self.components)},
        }


class UpdateDataModel(_Message):
    kind: Literal["updateDataModel"] = "updateDataModel"
    surface_id: str = Field(alias="surfaceId", min_length=1)
    path: str | None = None
    value: JsonValue = None

    def payload(self) -> JsonObject:
        body: JsonObject = {"surfaceId": self.surface_id}
        if self.path is not None:
            body["path"] = self.path
        if self.value is not None:
            body["value"] = self.value
        return {"version": A2UI_VERSION, "updateDataModel": body}


class DeleteSurface(_Message):
    kind: Literal["deleteSurface"] = "deleteSurface"
    surface_id: str = Field(alias="surfaceId", min_length=1)

    def payload(self) -> JsonObject:
        return {"version": A2UI_VERSION, "deleteSurface": {"surfaceId": self.surface_id}}


type ServerMessage = CreateSurface | UpdateComponents | UpdateDataModel | DeleteSurface


class Action(_Message):
    """A user action from a surface component (client to server)."""

    kind: Literal["action"] = "action"
    name: str
    surface_id: str = Field(alias="surfaceId")
    source_component_id: str = Field(alias="sourceComponentId")
    timestamp: str
    context: JsonObject = Field(default_factory=dict)

    def payload(self) -> JsonObject:
        return {
            "version": A2UI_VERSION,
            "action": {
                "name": self.name,
                "surfaceId": self.surface_id,
                "sourceComponentId": self.source_component_id,
                "timestamp": self.timestamp,
                "context": dict(self.context),
            },
        }


class ClientError(_Message):
    kind: Literal["error"] = "error"
    code: str
    surface_id: str = Field(alias="surfaceId")
    message: str
    path: str | None = None

    def payload(self) -> JsonObject:
        body: JsonObject = {
            "code": self.code,
            "surfaceId": self.surface_id,
            "message": self.message,
        }
        if self.path is not None:
            body["path"] = self.path
        return {"version": A2UI_VERSION, "error": body}


type ClientMessage = Action | ClientError

_SERVER_KEYS: dict[
    str, type[CreateSurface | UpdateComponents | UpdateDataModel | DeleteSurface]
] = {
    "createSurface": CreateSurface,
    "updateComponents": UpdateComponents,
    "updateDataModel": UpdateDataModel,
    "deleteSurface": DeleteSurface,
}


def parse_server_message(payload: JsonObject) -> ServerMessage:
    """Validate against ``server_to_client.json`` (components against the basic catalog),
    then build the typed message."""
    validate_payload(payload, direction="server_to_client")
    for key, model in _SERVER_KEYS.items():
        if key in payload:
            body = cast(JsonObject, payload[key])
            try:
                return model.model_validate(body)
            except ValidationError as exc:
                raise A2UIValidationError("A2UI message shape", error=str(exc)[:300]) from exc
    raise A2UIValidationError("A2UI message has no known key")


def parse_client_message(payload: JsonObject) -> ClientMessage:
    validate_payload(payload, direction="client_to_server")
    try:
        if "action" in payload:
            return Action.model_validate(cast(JsonObject, payload["action"]))
        return ClientError.model_validate(cast(JsonObject, payload["error"]))
    except ValidationError as exc:
        raise A2UIValidationError("A2UI client message shape", error=str(exc)[:300]) from exc


__all__ = [
    "A2UI_EXT_URI",
    "A2UI_MEDIA_TYPE",
    "A2UI_VERSION",
    "BASIC_CATALOG_ID",
    "Action",
    "ClientError",
    "ClientMessage",
    "CreateSurface",
    "DeleteSurface",
    "ServerMessage",
    "UpdateComponents",
    "UpdateDataModel",
    "parse_client_message",
    "parse_server_message",
]
