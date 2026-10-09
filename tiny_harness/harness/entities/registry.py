"""The registry: one place every entity is resolved from (R1.2, R1.3, R1.6, R1.7).

Derived from sherma's ``Registry[T]`` / ``RegistryEntry[T]`` with three deliberate
changes: one registry with a typed ``get`` instead of a subclass per kind; a remote
entry carries its protocol and is fetched by that protocol's adapter; and the version is
``None`` for unversioned kinds. Version resolution is sherma's: a PEP 440 specifier
selects among the concrete registered versions, ``"*"`` means the latest concrete one,
and an entry registered under ``"*"`` is the fallback when no concrete version matches.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Self

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, model_validator

from tiny_harness.errors import EntityNotFoundError, RegistryConflictError, VersionNotFoundError
from tiny_harness.harness.entities.base import (
    Entity,
    EntityKind,
    EntityRef,
    RemoteLocation,
    TransportProtocol,
)

WILDCARD = "*"


class RegistryEntry[T: Entity](BaseModel):
    """How an entity is obtained: an instance, a factory (called once, cached) or a
    remote location resolved by its protocol's adapter. Exactly one of the three."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ref: EntityRef
    instance: T | None = None
    factory: Callable[[], T | Awaitable[T]] | None = None
    remote: RemoteLocation | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        sources = [s is not None for s in (self.instance, self.factory, self.remote)]
        if sum(sources) != 1:
            raise ValueError("a registry entry needs exactly one of instance, factory or remote")
        return self


Fetcher = Callable[[RegistryEntry[Entity]], Awaitable[Entity]]
"""A protocol adapter that turns a remote entry into a live entity (R1.5)."""


def _widen[T: Entity](entry: RegistryEntry[T]) -> RegistryEntry[Entity]:
    """Every entity is an Entity; the registry stores the widened entry (invariance of generics)."""
    return RegistryEntry[Entity](
        ref=entry.ref, instance=entry.instance, factory=entry.factory, remote=entry.remote
    )


def _concrete(version: str | None) -> Version | None:
    if version is None or version == WILDCARD:
        return None
    try:
        return Version(version)
    except InvalidVersion:
        return None


def _specifier(spec: str) -> SpecifierSet:
    """A bare version means an exact match, as sherma normalises it."""
    try:
        if _concrete(spec) is not None:
            return SpecifierSet(f"=={spec}")
        return SpecifierSet(spec)
    except InvalidSpecifier as exc:
        raise VersionNotFoundError("invalid version specifier", specifier=spec) from exc


class Registry:
    """Entities by ``(kind, id)`` then version (R1.2); never substitutes a default (R1.3)."""

    def __init__(self, *, fetchers: Mapping[TransportProtocol, Fetcher] | None = None) -> None:
        self._entries: dict[str, dict[str | None, RegistryEntry[Entity]]] = {}
        self._resolved: dict[tuple[str, str | None], Entity] = {}
        self._fetchers: dict[TransportProtocol, Fetcher] = dict(fetchers or {})

    async def add[T: Entity](self, entry: RegistryEntry[T], *, override: bool = False) -> None:
        """Register an entry; a second registration of the same ``(id, version)`` is a
        ``RegistryConflictError`` unless ``override`` says the loading order allows it (R3.8)."""
        bucket = self._entries.setdefault(entry.ref.key, {})
        if entry.ref.version in bucket and not override:
            raise RegistryConflictError(
                "entity already registered",
                kind=entry.ref.kind.value,
                id=entry.ref.id,
                version=str(entry.ref.version),
            )
        bucket[entry.ref.version] = _widen(entry)
        self._resolved.pop((entry.ref.key, entry.ref.version), None)

    async def get[T: Entity](self, ref: EntityRef, kind: type[T]) -> T:
        """Resolve exactly one entity of type ``kind`` or raise a typed error (R1.3)."""
        entry = self._select(ref)
        entity = await self._resolve(entry)
        if not isinstance(entity, kind):
            raise EntityNotFoundError(
                "registered entity is not of the requested type",
                kind=ref.kind.value,
                id=ref.id,
                requested=kind.__name__,
            )
        return entity

    async def remove(self, ref: EntityRef) -> None:
        bucket = self._entries.get(ref.key)
        if bucket is None or ref.version not in bucket:
            raise EntityNotFoundError(
                "no such entity", kind=ref.kind.value, id=ref.id, version=str(ref.version)
            )
        del bucket[ref.version]
        self._resolved.pop((ref.key, ref.version), None)
        if not bucket:
            del self._entries[ref.key]

    def list(self, kind: EntityKind | None = None) -> Sequence[EntityRef]:
        refs = [e.ref for bucket in self._entries.values() for e in bucket.values()]
        if kind is not None:
            refs = [r for r in refs if r.kind is kind]
        return refs

    # --- internals ---------------------------------------------------------------------

    def _select(self, ref: EntityRef) -> RegistryEntry[Entity]:
        bucket = self._entries.get(ref.key)
        if not bucket:
            raise EntityNotFoundError("no such entity", kind=ref.kind.value, id=ref.id)
        if ref.version is None:
            if None in bucket:
                return bucket[None]
            raise VersionNotFoundError(
                "entity is versioned; a version is required", kind=ref.kind.value, id=ref.id
            )
        concrete: dict[str, RegistryEntry[Entity]] = {
            v: e for v, e in bucket.items() if v is not None and _concrete(v) is not None
        }
        if ref.version == WILDCARD:
            if concrete:
                latest = max(concrete, key=lambda v: Version(v))
                return concrete[latest]
        else:
            spec = _specifier(ref.version)
            matching = [v for v in concrete if spec.contains(Version(v), prereleases=True)]
            if matching:
                best = max(matching, key=lambda v: Version(v))
                return concrete[best]
        if WILDCARD in bucket:
            return bucket[WILDCARD]
        raise VersionNotFoundError(
            "no registered version satisfies the specifier",
            kind=ref.kind.value,
            id=ref.id,
            specifier=ref.version,
        )

    async def _resolve(self, entry: RegistryEntry[Entity]) -> Entity:
        cache_key = (entry.ref.key, entry.ref.version)
        if entry.instance is not None:
            return entry.instance
        cached = self._resolved.get(cache_key)
        if cached is not None:
            return cached
        if entry.factory is not None:
            produced = entry.factory()
            entity = await produced if inspect.isawaitable(produced) else produced
        else:
            assert entry.remote is not None
            fetcher = self._fetchers.get(entry.remote.protocol)
            if fetcher is None:
                raise EntityNotFoundError(
                    "no protocol adapter for the remote entity",
                    kind=entry.ref.kind.value,
                    id=entry.ref.id,
                    protocol=entry.remote.protocol.value,
                )
            entity = await fetcher(entry)
        self._resolved[cache_key] = entity
        return entity


__all__ = ["WILDCARD", "Fetcher", "Registry", "RegistryEntry"]
