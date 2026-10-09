"""Entity base, registry references and the registry (R1)."""

from tiny_harness.harness.entities.base import (
    Entity,
    EntityKind,
    EntityRef,
    RemoteLocation,
    TransportProtocol,
)
from tiny_harness.harness.entities.registry import WILDCARD, Fetcher, Registry, RegistryEntry

__all__ = [
    "WILDCARD",
    "Entity",
    "EntityKind",
    "EntityRef",
    "Fetcher",
    "Registry",
    "RegistryEntry",
    "RemoteLocation",
    "TransportProtocol",
]
