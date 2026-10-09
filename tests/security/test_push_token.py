"""Abuse case 6 (push configs): the callback token is encrypted at rest."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from tiny_harness.errors import ConfigError
from tiny_harness.harness.persistence import (
    PushConfigRecord,
    PushTokenCipher,
    RecordKind,
    SqliteStore,
)

KEY = SecretStr(base64.b64encode(b"k" * 32).decode())


async def test_push_token_encrypted_at_rest() -> None:
    cipher = PushTokenCipher(KEY)
    record = PushConfigRecord(
        id="t-1:cfg-1",
        context_id="ctx",
        task_id="t-1",
        created_at=datetime(2026, 10, 9, tzinfo=UTC),
        config_id="cfg-1",
        url="https://client.example/callback",
        token_ciphertext=cipher.encrypt("super-secret-callback-token"),
    )
    store = SqliteStore(":memory:")
    await store.put(record)
    raw = store.raw_row(RecordKind.PUSH_CONFIGS, "t-1:cfg-1")
    assert raw is not None and "super-secret-callback-token" not in str(raw)
    loaded = await store.get(PushConfigRecord, "t-1:cfg-1")
    assert (
        loaded is not None
        and cipher.decrypt(loaded.token_ciphertext) == "super-secret-callback-token"
    )
    assert cipher.encrypt("") == "" and cipher.decrypt("") == ""
    # a fresh nonce per encryption
    assert cipher.encrypt("x") != cipher.encrypt("x")


def test_push_key_must_be_base64_of_a_valid_aes_key() -> None:
    with pytest.raises(ConfigError) as info:
        PushTokenCipher(SecretStr("not base64!"))
    assert info.value.variable == "TINY_HARNESS_PUSH_KEY"
    with pytest.raises(ConfigError):
        PushTokenCipher(SecretStr(base64.b64encode(b"short").decode()))
