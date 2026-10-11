"""Push-config credentials at rest (issue-23): kept as supplied, protected by the store.

tiny-harness applies no cipher of its own (R3.1). The credential is masked wherever a
record is printed (abuse case 2), a row an earlier version stored encrypted is
recognised so it is never delivered (R4.1, abuse case 4), and a new SQLite file is
readable by its owner only (R3.2, abuse case 1).
"""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from tiny_harness.harness.persistence import PushConfigRecord, RecordKind, SqliteStore

TOKEN = "super-secret-callback-token"
AUTH = '{"scheme": "Bearer", "credentials": "cr3d"}'


def record(**fields: object) -> PushConfigRecord:
    return PushConfigRecord.model_validate(
        {
            "id": "t-1:cfg-1",
            "context_id": "ctx",
            "task_id": "t-1",
            "created_at": datetime(2026, 10, 9, tzinfo=UTC),
            "config_id": "cfg-1",
            "url": "https://client.example/callback",
            **fields,
        }
    )


async def test_push_credentials_are_stored_as_supplied() -> None:
    store = SqliteStore(":memory:")
    await store.put(record(token=SecretStr(TOKEN), authentication=SecretStr(AUTH)))
    raw = store.raw_row(RecordKind.PUSH_CONFIGS, "t-1:cfg-1")
    assert raw is not None
    assert raw["token"] == TOKEN and raw["authentication"] == AUTH
    assert "token_ciphertext" not in raw and "authentication_ciphertext" not in raw
    loaded = await store.get(PushConfigRecord, "t-1:cfg-1")
    assert loaded is not None and not loaded.legacy
    assert loaded.token.get_secret_value() == TOKEN
    assert loaded.authentication.get_secret_value() == AUTH


def test_push_credentials_are_masked_when_printed() -> None:
    pushed = record(token=SecretStr(TOKEN), authentication=SecretStr(AUTH))
    for shown in (repr(pushed), str(pushed), str(pushed.model_dump())):
        assert TOKEN not in shown and "cr3d" not in shown


def test_a_row_stored_encrypted_by_an_earlier_version_is_legacy() -> None:
    old = json.loads(record().model_dump_json())
    del old["token"], old["authentication"]
    old["token_ciphertext"] = "bm9uY2UuLi5jaXBoZXJ0ZXh0"
    assert PushConfigRecord.model_validate_json(json.dumps(old)).legacy
    old["token_ciphertext"], old["authentication_ciphertext"] = "", "YXV0aA=="
    assert PushConfigRecord.model_validate_json(json.dumps(old)).legacy
    old["authentication_ciphertext"] = ""  # registered with no credential: nothing lost
    assert not PushConfigRecord.model_validate_json(json.dumps(old)).legacy


def test_a_new_sqlite_store_is_readable_by_its_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "state" / "new.sqlite3"
    SqliteStore(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_existing_sqlite_store_keeps_its_mode(tmp_path: Path) -> None:
    path = tmp_path / "shared.sqlite3"
    SqliteStore(path).close()
    os.chmod(path, 0o640)
    SqliteStore(path).close()
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
