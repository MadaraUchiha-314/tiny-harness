"""The A2UI A2A extension at version 0.9.1 (R20.5, R20.6, abuse case 9)."""

from tiny_harness.interaction.a2ui.messages import (
    A2UI_EXT_URI,
    A2UI_MEDIA_TYPE,
    A2UI_VERSION,
    BASIC_CATALOG_ID,
    Action,
    ClientError,
    ClientMessage,
    CreateSurface,
    DeleteSurface,
    ServerMessage,
    UpdateComponents,
    UpdateDataModel,
    parse_client_message,
    parse_server_message,
)
from tiny_harness.interaction.a2ui.surfaces import SurfaceRegistry
from tiny_harness.interaction.a2ui.validation import A2UIValidationError, validate_payload

__all__ = [
    "A2UI_EXT_URI",
    "A2UI_MEDIA_TYPE",
    "A2UI_VERSION",
    "BASIC_CATALOG_ID",
    "A2UIValidationError",
    "Action",
    "ClientError",
    "ClientMessage",
    "CreateSurface",
    "DeleteSurface",
    "ServerMessage",
    "SurfaceRegistry",
    "UpdateComponents",
    "UpdateDataModel",
    "parse_client_message",
    "parse_server_message",
    "validate_payload",
]
