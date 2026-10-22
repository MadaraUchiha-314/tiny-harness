"""Media intake: validate, store and rewrite the file parts of an incoming A2A message
(issue-38 R1.3-R1.5, abuse cases 1-3 and 7, design critic 5).

``MediaIntake.extract`` checks every file part and, only when all pass, stores their bytes
and returns the message with each ``raw`` part replaced by a ``url`` part pointing at the
media route. Nothing is stored when any part is refused. ``guard`` is the one function
every ingress runs before redaction: a new turn extracts, a control refuses files, and a
delivery from a remote agent or a channel drops them with a note.

Checks, in order, per part: (1) a ``url`` part is refused and never fetched; (2) media
must be on; (3) the declared type, parameters stripped and lower-cased, must be in the
effective accepted set; (4) the part and the running message total must be within the
size limits; (5) the signature must match the declared type; (6) an image's header must
declare at most ``max_image_pixels``; (7) an audio file must hold only audio, of a
countable duration within ``max_audio_seconds``.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import ClassVar, Literal, cast

from a2a.types import Message, Part
from google.protobuf import json_format

from tiny_harness.config import MediaConfig
from tiny_harness.errors import TinyHarnessError
from tiny_harness.harness.media import sniff
from tiny_harness.harness.media.models import ACCEPTED, MediaKind
from tiny_harness.harness.media.store import MediaStore
from tiny_harness.jsontypes import JsonObject

MediaRejectReason = Literal[
    "too_large",
    "message_too_large",
    "type_not_accepted",
    "type_mismatch",
    "url_not_accepted",
    "image_too_large",
    "audio_too_long",
    "media_off",
    "not_audio_only",
    "audio_duration_unknown",
    "files_not_accepted",
]


class MediaRejected(TinyHarnessError):
    """A file part was refused; nothing was stored. ``reason`` says which check refused
    it, ``detail["limit"]`` the limit it passed (when there is one) and ``detail["part"]``
    the part's index in the message."""

    code: ClassVar[str] = "media.rejected"

    def __init__(self, message: str, *, reason: MediaRejectReason, **detail: str) -> None:
        super().__init__(message, reason=reason, **detail)
        self.reason: MediaRejectReason = reason


def is_file_part(part: Part) -> bool:
    """A part that carries a file: its bytes (``raw``) or a reference to them (``url``)."""
    return part.WhichOneof("content") in ("raw", "url")


def _declared(part: Part) -> str:
    return part.media_type.split(";", 1)[0].strip().lower()


def _label(part: Part, index: int) -> str:
    return repr(part.filename) if part.filename else f"part {index}"


def _metadata(part: Part) -> JsonObject:
    return cast(JsonObject, json_format.MessageToDict(part.metadata))


@dataclass(frozen=True)
class _Checked:
    """One file part that passed every check, ready to store."""

    index: int
    part: Part
    media_type: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


class MediaIntake:
    """Validates, stores and rewrites the file parts of a new turn's message."""

    def __init__(
        self,
        store: MediaStore,
        config: MediaConfig,
        *,
        base_url: str,
        accepted: Collection[str] = tuple(ACCEPTED),
    ) -> None:
        self.store = store
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.accepted = frozenset(accepted)

    def _check(self, part: Part, index: int, total: int) -> _Checked:
        label = _label(part, index)
        where = {"part": str(index)}
        if part.WhichOneof("content") == "url":
            raise MediaRejected(
                f"{label} is a URL; send the file's bytes", reason="url_not_accepted", **where
            )
        media_type = _declared(part)
        if media_type not in self.accepted:
            raise MediaRejected(
                f"{label} has type {media_type or 'none'!r}, which this agent does not accept",
                reason="type_not_accepted",
                **where,
            )
        raw = part.raw
        if len(raw) > self.config.max_file_bytes:
            limit = self.config.max_file_bytes
            raise MediaRejected(
                f"{label} is larger than the {limit}-byte limit per file",
                reason="too_large",
                limit=str(limit),
                **where,
            )
        if total > self.config.max_message_bytes:
            limit = self.config.max_message_bytes
            raise MediaRejected(
                f"the files of this message are larger than the {limit}-byte limit",
                reason="message_too_large",
                limit=str(limit),
                **where,
            )
        if sniff.detect(raw) != media_type:
            raise MediaRejected(
                f"{label} is not a {media_type} file", reason="type_mismatch", **where
            )
        if ACCEPTED[media_type] is MediaKind.IMAGE:
            return self._check_image(part, index, media_type, label)
        return self._check_audio(part, index, media_type, label)

    def _check_image(self, part: Part, index: int, media_type: str, label: str) -> _Checked:
        try:
            width, height = sniff.image_size(part.raw)
        except sniff.SniffError as exc:
            raise MediaRejected(
                f"{label}: the image header cannot be read",
                reason="type_mismatch",
                part=str(index),
            ) from exc
        limit = self.config.max_image_pixels
        if width * height > limit:
            raise MediaRejected(
                f"{label} is {width}x{height}, more than the {limit}-pixel limit",
                reason="image_too_large",
                limit=str(limit),
                part=str(index),
            )
        return _Checked(index, part, media_type, width=width, height=height)

    def _check_audio(self, part: Part, index: int, media_type: str, label: str) -> _Checked:
        limit = self.config.max_audio_seconds
        try:
            info = sniff.audio_info(part.raw, media_type, max_seconds=limit)
        except sniff.SniffError as exc:
            reason: MediaRejectReason = (
                exc.reason if exc.reason != "unreadable" else "audio_duration_unknown"
            )
            raise MediaRejected(
                f"{label}: {exc} (limit {limit} s)",
                reason=reason,
                limit=str(limit),
                part=str(index),
            ) from exc
        return _Checked(index, part, media_type, duration_ms=info.duration_ms)

    async def extract(self, message: Message, *, task_id: str) -> Message:
        """Validate every file part, store its bytes and return the message with each
        raw part replaced by a url part (``/media/<task>/<id>``, same media type and
        filename, part metadata += ``mediaId``, ``size`` and ``durationMs``, ``width``,
        ``height`` where known). All-or-nothing: every part is checked before any is
        stored, so a rejection stores nothing."""
        checked: list[_Checked] = []
        total = 0
        for index, part in enumerate(message.parts):
            if not is_file_part(part):
                continue
            total += len(part.raw)
            checked.append(self._check(part, index, total))
        if not checked:
            return message
        rewritten = {item.index: await self._store(item, task_id) for item in checked}
        out = Message()
        out.CopyFrom(message)
        del out.parts[:]
        for index, part in enumerate(message.parts):
            out.parts.append(rewritten.get(index, part))
        return out

    async def _store(self, item: _Checked, task_id: str) -> Part:
        voice = _metadata(item.part).get("voice") is True
        ref = await self.store.put(
            task_id,
            item.part.raw,
            media_type=item.media_type,
            name=item.part.filename,
            width=item.width,
            height=item.height,
            duration_ms=item.duration_ms,
            voice=voice,
        )
        part = Part(
            url=f"{self.base_url}/media/{task_id}/{ref.id}",
            media_type=item.media_type,
            filename=item.part.filename,
        )
        part.metadata.CopyFrom(item.part.metadata)
        added: JsonObject = {"mediaId": ref.id, "size": ref.size}
        for key, value in (
            ("durationMs", item.duration_ms),
            ("width", item.width),
            ("height", item.height),
        ):
            if value is not None:
                added[key] = value
        part.metadata.update(added)
        return part


GuardMode = Literal["extract", "refuse", "drop"]


def _drop_note(part: Part) -> Part:
    kind = _declared(part) or "unknown"
    return Part(
        text=f"[remote agent sent a {kind} file; files from remote agents are not supported]"
    )


async def guard(
    message: Message,
    *,
    allow: GuardMode,
    intake: MediaIntake | None = None,
    task_id: str = "",
) -> Message:
    """The media rule of one ingress, run before redaction (design critic 5):

    - ``extract`` (a new turn): ``intake.extract``; with no intake, media is off and a
      file part is refused (``media_off``), a URL part first (``url_not_accepted``);
    - ``refuse`` (a control): a file part is refused (``files_not_accepted``);
    - ``drop`` (a remote agent's or a channel's delivery): each file part is replaced by
      a text note saying files from remote agents are not supported.

    A message without file parts passes unchanged in every mode."""
    files = [part for part in message.parts if is_file_part(part)]
    if not files:
        return message
    if allow == "refuse":
        raise MediaRejected("controls carry no files", reason="files_not_accepted")
    if allow == "drop":
        out = Message()
        out.CopyFrom(message)
        del out.parts[:]
        for part in message.parts:
            out.parts.append(_drop_note(part) if is_file_part(part) else part)
        return out
    if intake is None:
        for index, part in enumerate(message.parts):
            if part.WhichOneof("content") == "url":
                raise MediaRejected(
                    f"{_label(part, index)} is a URL; send the file's bytes",
                    reason="url_not_accepted",
                    part=str(index),
                )
        raise MediaRejected("this agent accepts no files", reason="media_off")
    return await intake.extract(message, task_id=task_id)


__all__ = [
    "GuardMode",
    "MediaIntake",
    "MediaRejectReason",
    "MediaRejected",
    "guard",
    "is_file_part",
]
