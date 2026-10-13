"""``SecretRegistry`` (issue-36 abuse case 6): a redactor given the process registry masks
every running harness's secrets, follows registrations as they change, and keeps a value
two harnesses share until both have removed it."""

from __future__ import annotations

from pydantic import SecretStr

from tiny_harness.harness.security import MASK, Redactor, SecretRegistry


def test_a_registered_secret_is_masked_by_every_redactor() -> None:
    registry = SecretRegistry()
    a = Redactor(["key-of-agent-a"], registry=registry)
    registry.register([SecretStr("key-of-agent-b")])
    assert a.scrub_text("b uses key-of-agent-b") == f"b uses {MASK}"
    assert a.scrub_text("a uses key-of-agent-a") == f"a uses {MASK}"


def test_an_unregistered_secret_is_no_longer_masked() -> None:
    registry = SecretRegistry()
    redactor = Redactor(registry=registry)
    registry.register(["plainvalue1"])
    assert redactor.scrub_text("plainvalue1") == MASK
    registry.unregister(["plainvalue1"])
    assert redactor.scrub_text("plainvalue1") == "plainvalue1"


def test_a_shared_value_stays_until_both_remove_it() -> None:
    registry = SecretRegistry()
    redactor = Redactor(registry=registry)
    registry.register(["sharedvalue"])
    registry.register(["sharedvalue"])
    registry.unregister(["sharedvalue"])
    assert redactor.scrub_text("sharedvalue") == MASK
    registry.unregister(["sharedvalue"])
    assert redactor.scrub_text("sharedvalue") == "sharedvalue"


def test_a_longer_secret_is_masked_whole() -> None:
    registry = SecretRegistry()
    redactor = Redactor(["abcd"], registry=registry)
    registry.register(["abcdefgh"])
    assert redactor.scrub_text("abcdefgh") == MASK


def test_without_a_registry_only_its_own_secrets_are_masked() -> None:
    registry = SecretRegistry()
    registry.register(["someone-elses"])
    assert Redactor(["mine-only"]).scrub_text("someone-elses") == "someone-elses"
