"""``Harness`` lifecycle (issue-36 R1, design § Error handling): the constructor does no
I/O and checks the prefix; a harness starts once; nothing that exists only while it runs
is handed out before; a start that fails part-way undoes what it did, claims included."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from temporalio.client import Client

from tiny_harness.config import Settings
from tiny_harness.errors import (
    ConfigError,
    HarnessAlreadyStartedError,
    HarnessConflictError,
    HarnessNotStartedError,
    HarnessStoppedError,
)
from tiny_harness.harness.security import PROCESS_SECRETS
from tiny_harness.service import harness as harness_module
from tiny_harness.service.claims import PROCESS_CLAIMS
from tiny_harness.service.harness import Harness

ENV = {"OPENAI_API_KEY": "sk-lifecycle-secret"}


def settings(tmp_path: Path, agent: str = "a", base_url: str = "http://h/agents/a") -> Settings:
    path = tmp_path / f"{agent}.toml"
    path.write_text(
        f"""
[agent]
id = "{agent}"
[temporal]
mode = "embedded"
[server]
base_url = "{base_url}"
[store]
sqlite_path = "{tmp_path / agent}.sqlite3"
"""
    )
    return Settings.load(path, env=ENV)


class NamespacedClient:
    """Just enough of a Temporal client: the namespace it polls in."""

    def __init__(self, namespace: str = "default") -> None:
        self.namespace = namespace


class Boom(Exception):
    pass


async def broken_runtime(*args: object, **kwargs: object) -> None:
    raise Boom("the runtime could not be built")


def test_the_constructor_checks_the_prefix_without_io(tmp_path: Path) -> None:
    harness = Harness(settings(tmp_path), client=cast(Client, NamespacedClient()))
    assert (harness.prefix, harness.public_url) == ("/agents/a", "http://h/agents/a")
    with pytest.raises(ConfigError):
        Harness(settings(tmp_path), prefix="/agents/b")


def test_nothing_that_runs_is_handed_out_before_start(tmp_path: Path) -> None:
    harness = Harness(settings(tmp_path), client=cast(Client, NamespacedClient()))
    assert not harness.started
    with pytest.raises(HarnessNotStartedError):
        _ = harness.client
    with pytest.raises(HarnessNotStartedError):
        _ = harness.card
    assert harness.asgi_app() is harness.asgi_app()


async def test_a_failed_start_undoes_its_claims_and_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness_module, "build_runtime", broken_runtime)
    held = PROCESS_CLAIMS.held()
    harness = Harness(settings(tmp_path), client=cast(Client, NamespacedClient()))
    with pytest.raises(Boom):
        await harness.__aenter__()
    assert PROCESS_CLAIMS.held() == held
    assert "sk-lifecycle-secret" not in PROCESS_SECRETS.values()[1]
    with pytest.raises(HarnessStoppedError):  # a harness runs once
        await harness.__aenter__()


async def test_a_second_harness_with_the_same_id_does_not_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """issue-36 abuse case 4: the clash is found before anything connects."""
    calls: list[str] = []

    async def recording_runtime(*args: object, **kwargs: object) -> None:
        calls.append("built")
        raise Boom("stop here")

    monkeypatch.setattr(harness_module, "build_runtime", recording_runtime)
    from tiny_harness.service.claims import Claim

    first = Claim(
        agent_id="a", namespace="default", task_queue="a", store_path=tmp_path / "other.sqlite3"
    )
    PROCESS_CLAIMS.claim(first)
    try:
        with pytest.raises(HarnessConflictError):
            await Harness(settings(tmp_path), client=cast(Client, NamespacedClient())).__aenter__()
        assert calls == []
    finally:
        PROCESS_CLAIMS.release(first)


async def test_a_running_harness_cannot_start_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = Harness(settings(tmp_path), client=cast(Client, NamespacedClient()))

    async def started(stack: object) -> None:
        return None

    monkeypatch.setattr(harness, "_start", started)
    async with harness:
        with pytest.raises(HarnessAlreadyStartedError):
            await harness.__aenter__()
    assert not harness.started


async def test_the_claim_uses_the_namespace_of_the_callers_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Self-review round 1, finding 2: a caller's client polls in its own namespace, so two
    agents with different configured namespaces on one client still clash on one queue."""
    monkeypatch.setattr(harness_module, "build_runtime", broken_runtime)
    from tiny_harness.service.claims import Claim

    held = Claim(
        agent_id="holder", namespace="real", task_queue="a", store_path=tmp_path / "h.sqlite3"
    )
    PROCESS_CLAIMS.claim(held)
    try:
        client = cast(Client, NamespacedClient("real"))
        with pytest.raises(HarnessConflictError):  # settings say "default"; the client is "real"
            await Harness(settings(tmp_path), client=client).__aenter__()
    finally:
        PROCESS_CLAIMS.release(held)
