"""Media retention (issue-38 R6.2, R6.4): the retention sweep deletes media older than
``[retention] media``, and all of a task's media when the task's record is swept."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from a2a.types import Task

from tests.integration.durable.conftest import Harness
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore
from tiny_harness.harness.persistence import RecordKind, TaskRecord
from tiny_harness.service.durable.activities import Activities
from tiny_harness.service.durable.models import SweepIn

DAY = timedelta(days=1)


def age(store: FileMediaStore, task_id: str, media_id: str, days: int) -> None:
    then = (datetime.now(UTC) - days * DAY).timestamp()
    for path in (store.root / task_id).iterdir():
        if path.name.startswith(media_id):
            os.utime(path, (then, then))


async def test_the_sweep_deletes_old_media_and_the_media_of_swept_tasks(tmp_path: Path) -> None:
    media = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), tmp_path)
    h = Harness([], media_store=media)
    now = datetime.now(UTC)
    for task_id, created in (("old", now - 40 * DAY), ("new", now)):
        await h.store.put(
            TaskRecord(
                id=task_id,
                context_id="ctx",
                task_id=task_id,
                created_at=created,
                task=Task(id=task_id),
                state_name="COMPLETED",
            )
        )
    of_old_task = await media.put("old", b"\x89PNG", media_type="image/png")
    kept = await media.put("new", b"\x89PNG", media_type="image/png")
    expired = await media.put("new", b"\x89PNG", media_type="image/png")
    age(media, "new", expired.id, days=10)
    activities = Activities(
        h.engine,
        retention={RecordKind.TASKS: 30 * DAY},
        media_retention=7 * DAY,
    )

    out = await activities.retention_sweep(SweepIn(task_id="heartbeat", correlation_id="c"))

    assert out.deleted == {"tasks": 1, "media": 2}
    assert await media.lookup("old", of_old_task.id) is None
    assert await media.lookup("new", expired.id) is None
    assert await media.lookup("new", kept.id) == kept


async def test_without_a_media_store_the_sweep_reports_no_media(tmp_path: Path) -> None:
    h = Harness([])
    activities = Activities(h.engine, retention={RecordKind.TASKS: 30 * DAY})
    out = await activities.retention_sweep(SweepIn(task_id="heartbeat", correlation_id="c"))
    assert "media" not in out.deleted


async def test_purging_a_task_deletes_its_media(tmp_path: Path) -> None:
    from tests.unit.test_config_media import load
    from tiny_harness.service.commands import purge_media
    from tiny_harness.service.runtime import default_media_root

    settings = load(tmp_path, f'[media]\ndir = "{tmp_path / "media"}"')
    media = FileMediaStore(
        EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), default_media_root(settings)
    )
    ref = await media.put("t-1", b"\x89PNG", media_type="image/png")
    other = await media.put("t-2", b"\x89PNG", media_type="image/png")
    assert await purge_media(settings, task_id="t-1") == 1
    assert await media.lookup("t-1", ref.id) is None
    assert await media.lookup("t-2", other.id) == other
    off = tmp_path / "off"
    off.mkdir()
    assert await purge_media(load(off), task_id="t-2") == 0


async def test_purge_terminates_the_workflow_before_it_deletes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A running workflow can still write media (a spoken reply, a generated image) and
    rows: the purge stops it first, then deletes (self-review 2.4)."""
    from contextlib import asynccontextmanager

    from tests.unit.test_config_media import load
    from tiny_harness.service import commands

    order: list[str] = []

    class Handle:
        async def terminate(self, *, reason: str) -> None:
            order.append("terminate")

    class Client:
        def get_workflow_handle(self, task_id: str) -> Handle:
            return Handle()

    @asynccontextmanager
    async def client(settings: object) -> AsyncGenerator[Client]:
        yield Client()

    class Store:
        def __init__(self, path: object) -> None:
            pass

        async def purge_task(self, task_id: str) -> dict[RecordKind, int]:
            order.append("rows")
            return {}

    async def purge_media(settings: object, *, task_id: str) -> int:
        order.append("media")
        return 0

    monkeypatch.setattr(commands, "temporal_client", client)
    monkeypatch.setattr(commands, "SqliteStore", Store)
    monkeypatch.setattr(commands, "purge_media", purge_media)
    assert await commands.tasks_purge(load(tmp_path, "[media]"), task_id="t-1") == 0
    assert order == ["terminate", "rows", "media"]
