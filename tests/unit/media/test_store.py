"""The file media store (issue-38 R1.5, R4.2, R6.2, R6.4, abuse case 4, design critic 3):
atomic task-scoped objects with unguessable ids, and growing speech objects written by one
fenced writer per generation and read while they grow."""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.fixtures import media as fx
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import (
    PCM_MEDIA_TYPE,
    FileMediaStore,
    MediaFailed,
    MediaFenced,
    MediaInterrupted,
    MediaKind,
    MediaRef,
    MediaStore,
)

REF = EntityRef(kind=EntityKind.MEDIA_STORE, id="file")


@pytest.fixture
def store(tmp_path: Path) -> FileMediaStore:
    return FileMediaStore(REF, tmp_path / "media")


async def collect(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


# --- put / get / lookup -------------------------------------------------------------------


async def test_put_stores_bytes_and_a_ref(store: FileMediaStore) -> None:
    raw = fx.png(4, 3)
    ref = await store.put("task-1", raw, media_type="image/png", name="../photo.png", width=4)
    assert isinstance(store, MediaStore)
    assert re.fullmatch(r"[A-Za-z0-9_-]{24}", ref.id)
    assert ref.task_id == "task-1"
    assert ref.kind is MediaKind.IMAGE
    assert (ref.size, ref.name, ref.width) == (len(raw), "photo.png", 4)
    assert await store.get(ref) == raw
    assert await store.lookup("task-1", ref.id) == ref


async def test_ids_are_fresh_per_put(store: FileMediaStore) -> None:
    ids = {(await store.put("t", b"x", media_type="audio/wav")).id for _ in range(20)}
    assert len(ids) == 20


async def test_put_leaves_no_temporary_files(store: FileMediaStore, tmp_path: Path) -> None:
    ref = await store.put("t", fx.wav(0.1), media_type="audio/wav", voice=True, duration_ms=100)
    files = sorted(p.name for p in (tmp_path / "media" / "t").iterdir())
    assert files == sorted([ref.id, f"{ref.id}.json"])
    assert ref.voice and ref.duration_ms == 100


async def test_put_refuses_a_type_outside_the_allow_list(store: FileMediaStore) -> None:
    with pytest.raises(ValueError):
        await store.put("t", fx.SVG, media_type="image/svg+xml")


@pytest.mark.parametrize("bad", ["..", "../etc", "a/b", "", "x" * 129, "a\x00b", "."])
async def test_traversal_ids_are_refused(store: FileMediaStore, bad: str) -> None:
    assert await store.lookup(bad, "abc") is None
    assert await store.lookup("task", bad) is None
    with pytest.raises(ValueError):
        await store.put(bad, b"x", media_type="audio/wav")
    with pytest.raises(ValueError):
        await store.create("task", bad, media_type=PCM_MEDIA_TYPE)


async def test_lookup_of_an_unknown_or_other_tasks_id_is_none(store: FileMediaStore) -> None:
    ref = await store.put("task-a", b"x", media_type="audio/wav")
    assert await store.lookup("task-a", "nope") is None
    assert await store.lookup("task-b", ref.id) is None


async def test_get_of_a_missing_object_fails_closed(store: FileMediaStore) -> None:
    ghost = MediaRef(id="ghost", task_id="t", kind=MediaKind.IMAGE, media_type="image/png", size=1)
    with pytest.raises(FileNotFoundError):
        await store.get(ghost)


# --- retention --------------------------------------------------------------------------------


async def test_delete_task_removes_every_object(store: FileMediaStore, tmp_path: Path) -> None:
    for _ in range(3):
        await store.put("gone", b"x", media_type="audio/wav")
    kept = await store.put("kept", b"y", media_type="audio/wav")
    await store.create("gone", "speech1", media_type=PCM_MEDIA_TYPE)
    assert await store.delete_task("gone") == 4
    assert not (tmp_path / "media" / "gone").exists()
    assert await store.get(kept) == b"y"
    assert await store.delete_task("gone") == 0
    assert await store.delete_task("../kept") == 0


async def test_sweep_deletes_objects_older_than_the_cut(
    store: FileMediaStore, tmp_path: Path
) -> None:
    old = await store.put("t", b"old", media_type="audio/wav")
    new = await store.put("t", b"new", media_type="audio/wav")
    alone = await store.put("lonely", b"old", media_type="audio/wav")
    long_ago = time.time() - 40 * 86_400
    for ref in (old, alone):
        for path in (tmp_path / "media" / ref.task_id).glob(f"{ref.id}*"):
            os.utime(path, (long_ago, long_ago))
    assert await store.sweep(datetime.now(UTC) - timedelta(days=30)) == 2
    assert await store.lookup("t", old.id) is None
    assert await store.lookup("t", new.id) == new
    assert not (tmp_path / "media" / "lonely").exists()


async def test_sweep_survives_an_object_deleted_under_it(
    store: FileMediaStore, tmp_path: Path
) -> None:
    """A ref that goes between the listing and its stat (a purge, a second sweep) is
    skipped, not a failed sweep (self-review 2.6); a dangling link stands for it."""
    old = await store.put("t", b"old", media_type="audio/wav")
    long_ago = time.time() - 40 * 86_400
    for path in (tmp_path / "media" / "t").glob(f"{old.id}*"):
        os.utime(path, (long_ago, long_ago))
    (tmp_path / "media" / "t" / "ghost.json").symlink_to(tmp_path / "missing")
    assert await store.sweep(datetime.now(UTC) - timedelta(days=30)) == 1
    assert await store.lookup("t", old.id) is None


async def test_sweep_deletes_abandoned_temp_files(store: FileMediaStore, tmp_path: Path) -> None:
    """A writer that died between its temp file and the rename leaves ``.tmp-*``: the
    sweep deletes one older than an hour and keeps a fresh one (self-review 2.6)."""
    kept = await store.put("t", b"kept", media_type="audio/wav")
    folder = tmp_path / "media" / "t"
    stale, fresh = folder / ".tmp-0123456789abcdef", folder / ".tmp-fedcba9876543210"
    stale.write_bytes(b"partial")
    fresh.write_bytes(b"partial")
    two_hours_ago = time.time() - 7_200
    os.utime(stale, (two_hours_ago, two_hours_ago))
    assert await store.sweep(datetime.now(UTC) - timedelta(days=30)) == 0
    assert not stale.exists()
    assert fresh.exists()
    assert await store.get(kept) == b"kept"


# --- growing objects --------------------------------------------------------------------------


async def test_create_is_open_and_idempotent(store: FileMediaStore) -> None:
    ref = await store.create("t", "speech1", media_type=PCM_MEDIA_TYPE)
    assert (ref.kind, ref.size, ref.media_type) == (MediaKind.AUDIO, 0, PCM_MEDIA_TYPE)
    assert await store.create("t", "speech1", media_type=PCM_MEDIA_TYPE) == ref
    assert await store.lookup("t", "speech1") == ref


async def test_a_growing_object_is_read_while_it_grows(store: FileMediaStore) -> None:
    ref = await store.create("t", "s1", media_type=PCM_MEDIA_TYPE)
    reader = asyncio.create_task(collect(store.read_stream(ref, poll=0.01)))
    writer = await store.begin(ref)
    assert writer.generation == 1
    for chunk in (b"ab", b"cd", b"ef"):
        await writer.append(chunk)
        await asyncio.sleep(0.02)
    await writer.close()
    assert await asyncio.wait_for(reader, 2) == b"abcdef"
    done = await store.lookup("t", "s1")
    assert done is not None and done.size == 6
    assert await store.get(done) == b"abcdef"
    # Replay: a new reader gets the finished object from its start.
    assert await collect(store.read_stream(done, poll=0.01)) == b"abcdef"


async def test_an_appended_chunk_reaches_the_reader_within_two_polls(
    store: FileMediaStore,
) -> None:
    poll = 0.05
    ref = await store.create("t", "s1", media_type=PCM_MEDIA_TYPE)
    writer = await store.begin(ref)
    stream = store.read_stream(ref, poll=poll)
    await writer.append(b"first")
    assert await asyncio.wait_for(anext(stream), 1) == b"first"
    await asyncio.sleep(poll * 0.5)  # the reader is now inside a poll interval
    started = time.monotonic()
    pending = asyncio.ensure_future(anext(stream))
    await writer.append(b"second")
    assert await asyncio.wait_for(pending, 1) == b"second"
    assert time.monotonic() - started <= 2 * poll
    await writer.close()
    assert await collect(stream) == b""


async def test_a_stale_writer_is_fenced(store: FileMediaStore) -> None:
    ref = await store.create("t", "s1", media_type=PCM_MEDIA_TYPE)
    first = await store.begin(ref)
    await first.append(b"old")
    second = await store.begin(ref)
    assert second.generation == 2
    with pytest.raises(MediaFenced):
        await first.append(b"more")
    with pytest.raises(MediaFenced):
        await first.close()
    await second.append(b"new")
    await second.close()
    assert await collect(store.read_stream(ref, poll=0.01)) == b"new"


async def test_a_reader_is_interrupted_by_a_new_generation(store: FileMediaStore) -> None:
    ref = await store.create("t", "s1", media_type=PCM_MEDIA_TYPE)
    first = await store.begin(ref)
    await first.append(b"one")
    stream = store.read_stream(ref, poll=0.01)
    assert await anext(stream) == b"one"
    await store.begin(ref)  # a retry after a worker crash
    with pytest.raises(MediaInterrupted):
        await asyncio.wait_for(anext(stream), 2)


async def test_a_failed_object_fails_its_reader(store: FileMediaStore) -> None:
    ref = await store.create("t", "s1", media_type=PCM_MEDIA_TYPE)
    writer = await store.begin(ref)
    await writer.append(b"part")
    await writer.close(failed=True)
    with pytest.raises(MediaFailed):
        await collect(store.read_stream(ref, poll=0.01))


async def test_an_idle_object_interrupts_its_reader(store: FileMediaStore) -> None:
    ref = await store.create("t", "s1", media_type=PCM_MEDIA_TYPE)
    with pytest.raises(MediaInterrupted):
        await asyncio.wait_for(collect(store.read_stream(ref, poll=0.01, idle_timeout=0.1)), 2)


async def test_a_reader_waits_for_the_first_writer(store: FileMediaStore) -> None:
    ref = await store.create("t", "s1", media_type=PCM_MEDIA_TYPE)
    reader = asyncio.create_task(collect(store.read_stream(ref, poll=0.01, idle_timeout=2)))
    await asyncio.sleep(0.05)
    writer = await store.begin(ref)
    await writer.append(b"late")
    await writer.close()
    assert await asyncio.wait_for(reader, 2) == b"late"


async def test_read_stream_of_a_put_object_yields_its_bytes(store: FileMediaStore) -> None:
    raw = fx.wav(0.2)
    ref = await store.put("t", raw, media_type="audio/wav")
    assert await collect(store.read_stream(ref)) == raw


async def test_begin_refuses_an_object_that_is_not_growing(store: FileMediaStore) -> None:
    ref = await store.put("t", b"x", media_type="audio/wav")
    with pytest.raises(ValueError):
        await store.begin(ref)
