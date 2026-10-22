"""The task-scoped media store (issue-38 R1.5, R4.2, R6.2, R6.4, abuse case 4, design
critic 3).

Media bytes live here and nowhere else; everything that crosses workflow history carries a
``MediaRef``. ``FileMediaStore`` keeps ``<root>/<task_id>/<media_id>`` (the bytes) beside
``<media_id>.json`` (the ref), each written to a temporary file and ``os.replace``d, so a
reader never sees half an object. Both ids are checked against ``[A-Za-z0-9_-]{1,128}``
before they touch a path.

A *growing* object (a spoken reply) is created open and then written by one fenced writer
per generation: ``begin`` bumps ``<media_id>.gen`` and writes only ``<media_id>.g<n>``;
``<media_id>.state`` (``open`` / ``done:<n>`` / ``failed:<n>``) is replaced atomically.
A writer whose generation is superseded gets ``MediaFenced`` at its next chunk, so two
overlapping activity attempts never write the same file. ``read_stream`` follows one
generation while it grows.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import re
import secrets
import shutil
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Generator
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, ClassVar, Final

from tiny_harness.errors import TinyHarnessError
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef
from tiny_harness.harness.media.models import ACCEPTED, PCM_MEDIA_TYPE, MediaKind, MediaRef

_SAFE_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,128}")
_GENERATION_FILE: Final = re.compile(r"\.g[0-9]+")
_READ_CHUNK: Final = 64 * 1024
_OPEN: Final = "open"


class MediaFenced(TinyHarnessError):
    """A speech writer was superseded by a newer generation; it must stop writing."""

    code = "media.fenced"


class MediaInterrupted(TinyHarnessError):
    """A growing object's stream ended early: a newer generation started (a retry), or no
    byte arrived within the idle timeout. The surface may replay the URL."""

    code = "media.interrupted"


class MediaFailed(TinyHarnessError):
    """A growing object was closed as failed (speech unavailable)."""

    code = "media.failed"


def _checked(*ids: str) -> None:
    for value in ids:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError(f"media id {value!r} is not [A-Za-z0-9_-]{{1,128}}")


class SpeechWriter(ABC):
    """The one writer of one generation of a growing object."""

    generation: int

    @abstractmethod
    async def append(self, chunk: bytes) -> None:
        """Append ``chunk``; ``MediaFenced`` when a newer generation exists."""

    @abstractmethod
    async def close(self, *, failed: bool = False) -> None:
        """Finish this generation as done (or failed); ``MediaFenced`` when superseded."""


class MediaStore(Entity):
    """Where media bytes live, scoped by task (R1.5)."""

    kind: ClassVar[EntityKind] = EntityKind.MEDIA_STORE

    @abstractmethod
    async def put(
        self,
        task_id: str,
        data: bytes,
        *,
        media_type: str,
        name: str = "",
        **meta: int | bool | None,
    ) -> MediaRef:
        """Store ``data`` under a fresh, unguessable id; ``meta`` fills the ref's optional
        fields (``duration_ms``, ``width``, ``height``, ``voice``)."""

    @abstractmethod
    async def get(self, ref: MediaRef) -> bytes:
        """The bytes of a stored (or finished growing) object; ``FileNotFoundError``
        when there are none."""

    @abstractmethod
    async def lookup(self, task_id: str, media_id: str) -> MediaRef | None:
        """The ref of ``media_id`` in ``task_id``; ``None`` for an unknown or unsafe id."""

    @abstractmethod
    async def create(self, task_id: str, media_id: str, *, media_type: str) -> MediaRef:
        """Create a growing object, open and empty; idempotent for the same id."""

    @abstractmethod
    async def begin(self, ref: MediaRef) -> SpeechWriter:
        """Start a new generation of a growing object, fencing every older writer."""

    @abstractmethod
    def read_stream(
        self, ref: MediaRef, *, poll: float = 0.05, idle_timeout: float = 30.0
    ) -> AsyncIterator[bytes]:
        """The object's bytes; for a growing object, one generation's bytes as they are
        written, ending when it is done. ``MediaFailed`` when it fails;
        ``MediaInterrupted`` when a newer generation starts or nothing arrives within
        ``idle_timeout`` seconds."""

    @abstractmethod
    async def delete_task(self, task_id: str) -> int:
        """Delete every object of the task; the number deleted."""

    @abstractmethod
    async def sweep(self, older_than: datetime) -> int:
        """Delete every object created before ``older_than`` (retention); the number."""


class _Paths:
    """The files of one object."""

    def __init__(self, root: Path, task_id: str, media_id: str) -> None:
        _checked(task_id, media_id)
        self.folder = root / task_id
        self.data = self.folder / media_id
        self.meta = self.folder / f"{media_id}.json"
        self.gen = self.folder / f"{media_id}.gen"
        self.state = self.folder / f"{media_id}.state"
        self.lock = self.folder / f"{media_id}.lock"

    def generation(self, n: int) -> Path:
        return self.data.with_name(f"{self.data.name}.g{n}")

    def read_generation(self) -> int:
        try:
            return int(self.gen.read_text() or "0")
        except FileNotFoundError:
            return 0

    def read_state(self) -> str | None:
        try:
            return self.state.read_text()
        except FileNotFoundError:
            return None

    @contextlib.contextmanager
    def locked(self) -> Generator[None]:
        """An exclusive lock across processes (server and worker) for this object."""
        with self.lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(f".tmp-{secrets.token_hex(8)}")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


class _FileSpeechWriter(SpeechWriter):
    def __init__(self, paths: _Paths, ref: MediaRef, generation: int) -> None:
        self.generation = generation
        self._paths = paths
        self._ref = ref
        self._file: BinaryIO = paths.generation(generation).open("ab")

    def _fenced(self) -> bool:
        return self._paths.read_generation() != self.generation

    async def append(self, chunk: bytes) -> None:
        if self._fenced():
            self._file.close()
            raise MediaFenced("a newer generation of this object is being written")
        self._file.write(chunk)
        self._file.flush()

    async def close(self, *, failed: bool = False) -> None:
        self._file.close()
        await asyncio.to_thread(self._finish, failed)

    def _finish(self, failed: bool) -> None:
        paths = self._paths
        with paths.locked():
            if self._fenced():
                raise MediaFenced("a newer generation of this object is being written")
            if failed:
                _atomic_write(paths.state, f"failed:{self.generation}".encode())
                return
            source = paths.generation(self.generation)
            temp = paths.data.with_name(f".tmp-{secrets.token_hex(8)}")
            os.link(source, temp)  # the finished generation is served as <media_id>
            os.replace(temp, paths.data)
            done = self._ref.model_copy(update={"size": source.stat().st_size})
            _atomic_write(paths.meta, done.model_dump_json().encode())
            _atomic_write(paths.state, f"done:{self.generation}".encode())


class FileMediaStore(MediaStore):
    """The media store on a local (or shared) file system, under ``root``."""

    def __init__(self, ref: EntityRef, root: Path) -> None:
        super().__init__(ref)
        self.root = root

    def _folder(self, paths: _Paths) -> None:
        paths.folder.mkdir(mode=0o700, parents=True, exist_ok=True)

    async def put(
        self,
        task_id: str,
        data: bytes,
        *,
        media_type: str,
        name: str = "",
        **meta: int | bool | None,
    ) -> MediaRef:
        kind = ACCEPTED.get(media_type)
        if kind is None:
            raise ValueError(f"media type {media_type!r} is not accepted")
        media_id = secrets.token_urlsafe(18)
        paths = _Paths(self.root, task_id, media_id)
        ref = MediaRef.model_validate(
            {
                **meta,
                "id": media_id,
                "task_id": task_id,
                "kind": kind,
                "media_type": media_type,
                "size": len(data),
                "name": name,
            }
        )

        def write() -> None:
            self._folder(paths)
            _atomic_write(paths.data, data)
            _atomic_write(paths.meta, ref.model_dump_json().encode())

        await asyncio.to_thread(write)
        return ref

    async def get(self, ref: MediaRef) -> bytes:
        paths = _Paths(self.root, ref.task_id, ref.id)
        return await asyncio.to_thread(paths.data.read_bytes)

    async def lookup(self, task_id: str, media_id: str) -> MediaRef | None:
        try:
            paths = _Paths(self.root, task_id, media_id)
        except ValueError:
            return None
        try:
            ref = MediaRef.model_validate_json(paths.meta.read_bytes())
        except FileNotFoundError, ValueError:
            return None
        return ref if (ref.task_id, ref.id) == (task_id, media_id) else None

    async def create(self, task_id: str, media_id: str, *, media_type: str) -> MediaRef:
        paths = _Paths(self.root, task_id, media_id)
        kind = MediaKind.AUDIO if media_type == PCM_MEDIA_TYPE else ACCEPTED.get(media_type)
        if kind is None:
            raise ValueError(f"media type {media_type!r} is not accepted")
        ref = MediaRef(id=media_id, task_id=task_id, kind=kind, media_type=media_type, size=0)

        def write() -> MediaRef:
            self._folder(paths)
            with paths.locked():
                if paths.meta.exists():
                    return MediaRef.model_validate_json(paths.meta.read_bytes())
                _atomic_write(paths.state, _OPEN.encode())
                _atomic_write(paths.meta, ref.model_dump_json().encode())
                return ref

        return await asyncio.to_thread(write)

    async def begin(self, ref: MediaRef) -> SpeechWriter:
        paths = _Paths(self.root, ref.task_id, ref.id)

        def start() -> int:
            with paths.locked():
                if paths.read_state() is None:
                    raise ValueError("not a growing object")
                generation = paths.read_generation() + 1
                paths.generation(generation).write_bytes(b"")
                _atomic_write(paths.gen, str(generation).encode())
                _atomic_write(paths.state, _OPEN.encode())
                return generation

        generation = await asyncio.to_thread(start)
        return _FileSpeechWriter(paths, ref, generation)

    async def read_stream(
        self, ref: MediaRef, *, poll: float = 0.05, idle_timeout: float = 30.0
    ) -> AsyncIterator[bytes]:
        paths = _Paths(self.root, ref.task_id, ref.id)
        if paths.read_state() is None:
            with paths.data.open("rb") as handle:
                while chunk := handle.read(_READ_CHUNK):
                    yield chunk
            return
        last_byte = time.monotonic()

        def idle() -> bool:
            return time.monotonic() - last_byte > idle_timeout

        generation = paths.read_generation()
        while not generation:  # created, no writer yet
            if idle():
                raise MediaInterrupted("no speech arrived")
            await asyncio.sleep(poll)
            generation = paths.read_generation()
        with paths.generation(generation).open("rb") as handle:
            while True:
                chunk = handle.read(_READ_CHUNK)
                if chunk:
                    last_byte = time.monotonic()
                    yield chunk
                    continue
                state = paths.read_state()
                if state == f"done:{generation}":
                    while tail := handle.read(_READ_CHUNK):
                        yield tail
                    return
                if state == f"failed:{generation}":
                    raise MediaFailed("speech failed")
                if paths.read_generation() != generation:
                    raise MediaInterrupted("a newer generation started")
                if idle():
                    raise MediaInterrupted("no speech arrived")
                await asyncio.sleep(poll)

    async def delete_task(self, task_id: str) -> int:
        if not _SAFE_ID.fullmatch(task_id):
            return 0
        folder = self.root / task_id

        def delete() -> int:
            if not folder.is_dir():
                return 0
            count = sum(1 for _ in folder.glob("*.json"))
            shutil.rmtree(folder)
            return count

        return await asyncio.to_thread(delete)

    async def sweep(self, older_than: datetime) -> int:
        cut = older_than.timestamp()

        def sweep() -> int:
            if not self.root.is_dir():
                return 0
            count = 0
            for folder in self.root.iterdir():
                if not folder.is_dir() or not _SAFE_ID.fullmatch(folder.name):
                    continue
                for meta in list(folder.glob("*.json")):
                    if meta.stat().st_mtime < cut:
                        _delete_object(folder, meta.name.removesuffix(".json"))
                        count += 1
                with contextlib.suppress(OSError):
                    folder.rmdir()  # only when it is empty
            return count

        return await asyncio.to_thread(sweep)


def _delete_object(folder: Path, media_id: str) -> None:
    """Every file of one object: exact names, so ``s1`` never takes ``s10`` with it."""
    for path in folder.iterdir():
        name = path.name
        if name == media_id or (
            name.startswith(media_id + ".")
            and (
                name[len(media_id) :] in (".json", ".gen", ".state", ".lock")
                or _GENERATION_FILE.fullmatch(name[len(media_id) :])
            )
        ):
            path.unlink(missing_ok=True)


__all__ = [
    "FileMediaStore",
    "MediaFailed",
    "MediaFenced",
    "MediaInterrupted",
    "MediaStore",
    "SpeechWriter",
]
