"""The persistence store entity and the default SQLite store (R11.1-R11.3).

``Store`` is the interface a plugin implements for a production database; ``SqliteStore``
is the default on the standard library's ``sqlite3``: one table per record kind with the
record's JSON and indexed id, context, task and timestamp columns, every call run through
``asyncio.to_thread`` under one lock. A failed write is a ``StoreWriteError``; the caller
never reports its operation complete. ``sweep`` applies the retention policy per kind.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from abc import abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

from tiny_harness.errors import StoreWriteError
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef
from tiny_harness.harness.persistence.records import (
    RECORD_TYPES,
    Filter,
    RecordBase,
    RecordKind,
    kind_of,
)
from tiny_harness.jsontypes import JsonObject


class Store(Entity):
    """Put, get, query and sweep typed records."""

    kind = EntityKind.STORE

    @abstractmethod
    async def put(self, record: RecordBase) -> None: ...

    @abstractmethod
    async def get[R: RecordBase](self, record_type: type[R], id: str) -> R | None: ...

    @abstractmethod
    async def query[R: RecordBase](self, record_type: type[R], where: Filter) -> Sequence[R]: ...

    @abstractmethod
    async def delete(self, record_type: type[RecordBase], id: str) -> bool: ...

    @abstractmethod
    async def sweep(
        self, retention: Mapping[RecordKind, timedelta], now: datetime
    ) -> dict[RecordKind, int]: ...


def _kind_for(record_type: type[RecordBase]) -> RecordKind:
    for kind, cls in RECORD_TYPES.items():
        if cls is record_type:
            return kind
    raise TypeError(f"unknown record type {record_type.__name__}")


class SqliteStore(Store):
    """The default store. ``path`` may be ``":memory:"`` for tests."""

    def __init__(self, path: Path | str, *, ref: EntityRef | None = None) -> None:
        super().__init__(ref or EntityRef(kind=EntityKind.STORE, id="sqlite", version=None))
        self._path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        for kind in RecordKind:
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS {kind.value} ("
                "id TEXT PRIMARY KEY, context_id TEXT NOT NULL, task_id TEXT NOT NULL, "
                "created_at TEXT NOT NULL, json TEXT NOT NULL)"
            )
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS {kind.value}_context ON {kind.value}(context_id)"
            )
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS {kind.value}_task ON {kind.value}(task_id)"
            )
            self._conn.execute(
                f"CREATE INDEX IF NOT EXISTS {kind.value}_created ON {kind.value}(created_at)"
            )
        self._conn.commit()

    async def put(self, record: RecordBase) -> None:
        kind = kind_of(record)
        payload = record.model_dump_json()

        def write() -> None:
            with self._lock:
                try:
                    self._conn.execute(
                        f"INSERT OR REPLACE INTO {kind.value} "
                        "(id, context_id, task_id, created_at, json) VALUES (?, ?, ?, ?, ?)",
                        (
                            record.id,
                            record.context_id,
                            record.task_id,
                            record.created_at.isoformat(),
                            payload,
                        ),
                    )
                    self._conn.commit()
                except sqlite3.Error as exc:
                    raise StoreWriteError(
                        f"sqlite write failed: {exc}", kind=kind.value, id=record.id
                    ) from exc

        await asyncio.to_thread(write)

    async def get[R: RecordBase](self, record_type: type[R], id: str) -> R | None:
        kind = _kind_for(record_type)

        def read() -> str | None:
            with self._lock:
                row = self._conn.execute(
                    f"SELECT json FROM {kind.value} WHERE id = ?", (id,)
                ).fetchone()
            return cast(str, row[0]) if row else None

        raw = await asyncio.to_thread(read)
        return record_type.model_validate_json(raw) if raw is not None else None

    async def query[R: RecordBase](self, record_type: type[R], where: Filter) -> Sequence[R]:
        kind = _kind_for(record_type)
        clauses: list[str] = []
        params: list[str | int] = []
        if where.context_id is not None:
            clauses.append("context_id = ?")
            params.append(where.context_id)
        if where.task_id is not None:
            clauses.append("task_id = ?")
            params.append(where.task_id)
        if where.since is not None:
            clauses.append("created_at > ?")
            params.append(where.since.isoformat())
        sql = f"SELECT json FROM {kind.value}"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC, id ASC LIMIT ?"
        params.append(where.limit)

        def read() -> list[str]:
            with self._lock:
                return [cast(str, r[0]) for r in self._conn.execute(sql, params).fetchall()]

        return [record_type.model_validate_json(raw) for raw in await asyncio.to_thread(read)]

    async def delete(self, record_type: type[RecordBase], id: str) -> bool:
        kind = _kind_for(record_type)

        def remove() -> bool:
            with self._lock:
                cursor = self._conn.execute(f"DELETE FROM {kind.value} WHERE id = ?", (id,))
                self._conn.commit()
                return cursor.rowcount > 0

        return await asyncio.to_thread(remove)

    async def sweep(
        self, retention: Mapping[RecordKind, timedelta], now: datetime
    ) -> dict[RecordKind, int]:
        def run() -> dict[RecordKind, int]:
            deleted: dict[RecordKind, int] = {}
            with self._lock:
                for kind, ttl in retention.items():
                    cutoff = (now - ttl).isoformat()
                    cursor = self._conn.execute(
                        f"DELETE FROM {kind.value} WHERE created_at < ?", (cutoff,)
                    )
                    deleted[kind] = cursor.rowcount
                self._conn.commit()
            return deleted

        return await asyncio.to_thread(run)

    async def purge_task(self, task_id: str) -> dict[RecordKind, int]:
        """Delete every record of one task (the ``tasks purge`` command)."""

        def run() -> dict[RecordKind, int]:
            deleted: dict[RecordKind, int] = {}
            with self._lock:
                for kind in RecordKind:
                    cursor = self._conn.execute(
                        f"DELETE FROM {kind.value} WHERE task_id = ?", (task_id,)
                    )
                    deleted[kind] = cursor.rowcount
                self._conn.commit()
            return deleted

        return await asyncio.to_thread(run)

    def raw_row(self, kind: RecordKind, id: str) -> JsonObject | None:
        """The stored JSON as written (tests use it to check what is on disk)."""
        with self._lock:
            row = self._conn.execute(
                f"SELECT json FROM {kind.value} WHERE id = ?", (id,)
            ).fetchone()
        return cast(JsonObject, json.loads(cast(str, row[0]))) if row else None

    def close(self) -> None:
        self._conn.close()


__all__ = ["SqliteStore", "Store"]
