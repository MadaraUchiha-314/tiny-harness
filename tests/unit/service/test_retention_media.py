"""Media retention (issue-38 R6.2, R6.4): the retention sweep deletes media older than
``[retention] media``, and all of a task's media when the task's record is swept."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
