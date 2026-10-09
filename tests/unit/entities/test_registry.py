"""The registry (R1.2, R1.3, R1.6, R1.7).

(id, version) resolution, local and remote entries, conflicts and overrides.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import HttpUrl, ValidationError

from tiny_harness.errors import EntityNotFoundError, RegistryConflictError, VersionNotFoundError
from tiny_harness.harness.entities import (
    Entity,
    EntityKind,
    EntityRef,
    Registry,
    RegistryEntry,
    RemoteLocation,
    TransportProtocol,
)


class Prompt(Entity):
    kind = EntityKind.PROMPT

    def __init__(self, ref: EntityRef, text: str = "") -> None:
        super().__init__(ref)
        self.text = text


class Channel(Entity):
    kind = EntityKind.CHANNEL


def prompt(version: str | None, text: str = "") -> RegistryEntry[Prompt]:
    ref = EntityRef(kind=EntityKind.PROMPT, id="system", version=version)
    return RegistryEntry[Prompt](ref=ref, instance=Prompt(ref, text))


def test_entry_needs_exactly_one_of_instance_factory_remote() -> None:
    ref = EntityRef(kind=EntityKind.PROMPT, id="p", version="1.0.0")
    with pytest.raises(ValidationError, match="exactly one"):
        RegistryEntry[Prompt](ref=ref)
    with pytest.raises(ValidationError, match="exactly one"):
        RegistryEntry[Prompt](
            ref=ref,
            instance=Prompt(ref),
            remote=RemoteLocation(url=HttpUrl("https://x.example"), protocol=TransportProtocol.A2A),
        )


async def test_get_returns_the_instance_and_lists_refs() -> None:
    registry = Registry()
    await registry.add(prompt("1.0.0", "one"))
    got = await registry.get(
        EntityRef(kind=EntityKind.PROMPT, id="system", version="1.0.0"), Prompt
    )
    assert got.text == "one"
    assert registry.list(EntityKind.PROMPT) == [
        EntityRef(kind=EntityKind.PROMPT, id="system", version="1.0.0")
    ]
    assert registry.list(EntityKind.TOOL) == []


async def test_unknown_id_raises_not_found_never_a_default() -> None:
    registry = Registry()
    with pytest.raises(EntityNotFoundError):
        await registry.get(EntityRef(kind=EntityKind.PROMPT, id="missing", version="*"), Prompt)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("*", "2.1.0"),
        ("1.0.0", "1.0.0"),
        ("==1.2.0", "1.2.0"),
        (">=1.1,<2", "1.2.0"),
        ("~=1.0", "1.2.0"),
    ],
)
async def test_version_specifiers_resolve_like_sherma(spec: str, expected: str) -> None:
    registry = Registry()
    for v in ("1.0.0", "1.2.0", "2.1.0"):
        await registry.add(prompt(v, v))
    got = await registry.get(EntityRef(kind=EntityKind.PROMPT, id="system", version=spec), Prompt)
    assert got.text == expected


async def test_no_matching_version_raises_version_not_found() -> None:
    registry = Registry()
    await registry.add(prompt("1.0.0"))
    with pytest.raises(VersionNotFoundError):
        await registry.get(EntityRef(kind=EntityKind.PROMPT, id="system", version=">=3"), Prompt)


async def test_wildcard_registration_is_the_fallback() -> None:
    registry = Registry()
    await registry.add(prompt("*", "fallback"))
    await registry.add(prompt("1.0.0", "one"))
    exact = await registry.get(
        EntityRef(kind=EntityKind.PROMPT, id="system", version="1.0.0"), Prompt
    )
    other = await registry.get(
        EntityRef(kind=EntityKind.PROMPT, id="system", version="9.9.9"), Prompt
    )
    assert (exact.text, other.text) == ("one", "fallback")


async def test_unversioned_kinds_use_version_none() -> None:
    registry = Registry()
    ref = EntityRef(kind=EntityKind.CHANNEL, id="task-7")
    await registry.add(RegistryEntry[Channel](ref=ref, instance=Channel(ref)))
    assert (await registry.get(ref, Channel)).ref == ref
    with pytest.raises(VersionNotFoundError):
        await registry.get(
            EntityRef(kind=EntityKind.CHANNEL, id="task-7", version="1.0.0"), Channel
        )


async def test_duplicate_registration_conflicts_unless_overridden() -> None:
    registry = Registry()
    await registry.add(prompt("1.0.0", "first"))
    with pytest.raises(RegistryConflictError):
        await registry.add(prompt("1.0.0", "second"))
    await registry.add(prompt("1.0.0", "second"), override=True)
    got = await registry.get(
        EntityRef(kind=EntityKind.PROMPT, id="system", version="1.0.0"), Prompt
    )
    assert got.text == "second"


async def test_factory_is_called_once_and_cached() -> None:
    calls = 0

    async def build() -> Prompt:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return Prompt(ref, "built")

    ref = EntityRef(kind=EntityKind.PROMPT, id="system", version="1.0.0")
    registry = Registry()
    await registry.add(RegistryEntry[Prompt](ref=ref, factory=build))
    assert (await registry.get(ref, Prompt)).text == "built"
    assert (await registry.get(ref, Prompt)).text == "built"
    assert calls == 1


async def test_remote_entry_is_fetched_by_its_protocol_adapter() -> None:
    ref = EntityRef(kind=EntityKind.PROMPT, id="remote", version="1.0.0")
    remote = RemoteLocation(
        url=HttpUrl("https://prompts.example/system"), protocol=TransportProtocol.HTTPS
    )

    async def fetch(entry: RegistryEntry[Entity]) -> Entity:
        assert entry.remote is remote
        return Prompt(entry.ref, "fetched")

    registry = Registry(fetchers={TransportProtocol.HTTPS: fetch})
    await registry.add(RegistryEntry[Prompt](ref=ref, remote=remote))
    assert (await registry.get(ref, Prompt)).text == "fetched"


async def test_remote_entry_without_an_adapter_fails_closed() -> None:
    ref = EntityRef(kind=EntityKind.PROMPT, id="remote", version="1.0.0")
    remote = RemoteLocation(
        url=HttpUrl("https://prompts.example/system"), protocol=TransportProtocol.MCP
    )
    registry = Registry()
    await registry.add(RegistryEntry[Prompt](ref=ref, remote=remote))
    with pytest.raises(EntityNotFoundError, match="adapter"):
        await registry.get(ref, Prompt)


async def test_get_with_the_wrong_kind_is_not_found() -> None:
    registry = Registry()
    await registry.add(prompt("1.0.0"))
    with pytest.raises(EntityNotFoundError):
        await registry.get(EntityRef(kind=EntityKind.PROMPT, id="system", version="1.0.0"), Channel)


async def test_remove_drops_one_version() -> None:
    registry = Registry()
    await registry.add(prompt("1.0.0"))
    await registry.add(prompt("2.0.0"))
    await registry.remove(EntityRef(kind=EntityKind.PROMPT, id="system", version="2.0.0"))
    assert [r.version for r in registry.list(EntityKind.PROMPT)] == ["1.0.0"]
    with pytest.raises(EntityNotFoundError):
        await registry.remove(EntityRef(kind=EntityKind.PROMPT, id="system", version="2.0.0"))
