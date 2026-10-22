"""Media in the TUI (issue-38 R1.2, R2.4, R6.3, design critic 8): attachments checked
against the card before they become chips, the id-keyed no-follow cache, and the
conversation entries for images and audio.

An image is drawn inline WHERE the ``images`` extra (``textual-image``) is installed and
the terminal speaks a graphics protocol (kitty's, or sixel, which iTerm2 also speaks);
otherwise it is one line naming where the file was saved. The original file name is
display text only: the cache path is built from the task and media ids the TUI parsed
from the URL, both checked against ``[A-Za-z0-9_-]{1,128}``.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re
import secrets
import stat
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Final, cast
from urllib.parse import urlsplit

from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from tiny_harness.harness.media import ACCEPTED, PCM_MEDIA_TYPE, MediaKind, sniff
from tiny_harness.harness.media.extension import MEDIA_ROUTE, MediaExtensionParams
from tiny_harness.interaction.tui.client import Attachment
from tiny_harness.interaction.tui.voice import meter

MEDIA_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,128}")
EXTENSIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "audio/webm": ".webm",
        PCM_MEDIA_TYPE: ".pcm",
    }
)
"""The cache file's extension, from the media type alone."""
DEFAULT_CACHE_ROOT: Final = Path("~/.cache/tiny-harness/media")
NO_GRAPHICS: Final = "(this terminal has no graphics protocol; open the file to view it)"
PLAY_HINT: Final = "⏎ to play"
SAVE_HINT: Final = "⏎ saves"
PLAYABLE_AUDIO: Final = "audio/wav"
"""The one audio type the TUI decodes and plays; Enter saves any other to the cache."""
TIMES: Final = "\u00d7"  # the multiplication sign of "1024 x 768"

type ImageView = Callable[[Path], Widget]
"""Draws an image file inline; ``None`` where the terminal cannot."""


# --- text ----------------------------------------------------------------------------------


def human_size(size: int) -> str:
    """``940 KB``, ``1.8 MB``, ``48 MB`` (binary units, as file managers show them)."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{round(size / 1024)} KB"
    megabytes = size / (1024 * 1024)
    return f"{megabytes:.1f} MB" if megabytes < 10 else f"{round(megabytes)} MB"


def limit_text(size: int) -> str:
    """A configured limit: ``20 MiB`` when it is whole mebibytes, else bytes."""
    mib = 1024 * 1024
    return f"{size // mib} MiB" if size >= mib and size % mib == 0 else f"{size} bytes"


def clock(duration_ms: int) -> str:
    seconds = round(duration_ms / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def kind_of(media_type: str) -> str:
    """``image`` or ``audio`` (the spoken-reply type is audio)."""
    if media_type == PCM_MEDIA_TYPE:
        return MediaKind.AUDIO.value
    kind = ACCEPTED.get(media_type)
    return kind.value if kind is not None else "file"


def chip_text(attachment: Attachment) -> str:
    """``[image] sofa.jpg · 940 KB``, ``[audio] note.m4a · 0:12``."""
    label = "voice" if attachment.voice else attachment.kind
    if attachment.duration_ms is not None:
        return f"[{label}] {attachment.name} · {clock(attachment.duration_ms)}"
    return f"[{label}] {attachment.name} · {human_size(attachment.size)}"


def short(identifier: str) -> str:
    return f"{identifier[:4]}…{identifier[-2:]}" if len(identifier) > 8 else identifier


# --- attaching -----------------------------------------------------------------------------


class AttachRefused(ValueError):
    """A file the card's limits refuse; the message names the file and the limit."""


def load_attachment(
    path: Path, params: MediaExtensionParams | None, pending: Sequence[Attachment] = ()
) -> Attachment:
    """Read ``path`` and check it as the server will (type by signature, size per file and
    per message, image header, audio duration), so a refusal shows before anything is
    sent. The server checks again; this only gives early feedback."""
    name = path.name
    if params is None or not params.input:
        raise AttachRefused("this agent accepts no files")
    try:
        info = path.stat()
    except OSError as exc:
        raise AttachRefused(f"{name}: {exc.strerror or 'cannot be read'}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise AttachRefused(f"{name} is not a file")
    if params.max_file_bytes and info.st_size > params.max_file_bytes:
        raise AttachRefused(
            f"{name} is {human_size(info.st_size)}; "
            f"the limit is {limit_text(params.max_file_bytes)} per file"
        )
    total = info.st_size + sum(a.size for a in pending)
    if params.max_message_bytes and total > params.max_message_bytes:
        raise AttachRefused(
            f"{name} brings this message to {human_size(total)}; "
            f"the limit is {limit_text(params.max_message_bytes)} per message"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise AttachRefused(f"{name}: {exc.strerror or 'cannot be read'}") from exc
    media_type = sniff.detect(data)
    if media_type is None or media_type not in params.input:
        accepted = ", ".join(t.split("/", 1)[1] for t in params.input)
        raise AttachRefused(f"{name} is not a file this agent accepts ({accepted})")
    if ACCEPTED[media_type] is MediaKind.IMAGE:
        try:
            width, height = sniff.image_size(data)
        except sniff.SniffError as exc:
            raise AttachRefused(f"{name}: the image header cannot be read") from exc
        return Attachment(name, media_type, data, width=width, height=height)
    try:
        audio = sniff.audio_info(data, media_type, max_seconds=params.max_audio_seconds)
    except sniff.SniffError as exc:
        if exc.reason == "audio_too_long":
            raise AttachRefused(
                f"{name} is longer than {params.max_audio_seconds} s, the limit"
            ) from exc
        raise AttachRefused(f"{name}: {exc}") from exc
    return Attachment(name, media_type, data, duration_ms=audio.duration_ms)


def complete_path(partial: str) -> str | None:
    """The first directory entry that completes ``partial`` (``~`` kept as typed); a
    directory gets a trailing ``/``. Hidden entries only when asked for with a ``.``."""
    folder, separator, prefix = partial.rpartition("/")
    base = Path(os.path.expanduser(folder or "/")) if separator else Path()
    head = f"{folder}/" if separator else ""
    try:
        names = sorted(entry.name for entry in os.scandir(base))
    except OSError:
        return None
    for entry in names:
        if not entry.startswith(prefix) or (entry.startswith(".") and not prefix.startswith(".")):
            continue
        suffix = "/" if (base / entry).is_dir() else ""
        return f"{head}{entry}{suffix}"
    return None


def rejection_text(attachment: Attachment, reason: str, limit: str | None, fallback: str) -> str:
    """The server's refusal of one file, as the error line says it."""
    name = attachment.name
    if reason == "too_large" and limit and limit.isdigit():
        size = human_size(attachment.size)
        return f"{name} is {size}; the limit is {limit_text(int(limit))} per file"
    if reason == "message_too_large" and limit and limit.isdigit():
        return f"the files are larger than {limit_text(int(limit))} per message"
    if reason == "audio_too_long" and limit:
        return f"{name} is longer than {limit} s, the limit"
    if reason == "not_audio_only":
        return f"{name} holds more than audio; only audio is accepted"
    if reason == "audio_codec_not_accepted":
        return f"{name} uses an audio codec this agent does not accept"
    if reason in ("type_not_accepted", "type_mismatch"):
        return f"{name} is not a file this agent accepts"
    return fallback


# --- the cache -----------------------------------------------------------------------------


class MediaCacheError(OSError):
    """A cache write refused: a bad id, an unknown type, or a symlink in the way."""


def media_ids(url: str, media_path: str = MEDIA_ROUTE) -> tuple[str, str] | None:
    """``(task_id, media_id)`` of ``<agent><media_path>/<task>/<id>``, both checked; any
    other URL is ``None``."""
    path = urlsplit(url).path
    marker = media_path.rstrip("/") + "/"
    at = path.rfind(marker)
    if at < 0:
        return None
    pieces = path[at + len(marker) :].split("/")
    if len(pieces) != 2 or any(MEDIA_ID.fullmatch(p) is None for p in pieces):
        return None
    return pieces[0], pieces[1]


def pinned_media_ids(
    url: str, *, agent_url: str, task_id: str, media_path: str = MEDIA_ROUTE
) -> tuple[str, str] | None:
    """``(task_id, media_id)`` only for exactly ``<agent_url><media_path>/<task_id>/<id>``
    (critic 8): the agent's origin, the route under the agent's path with no query or
    fragment, valid ids, and the task on screen. Any other URL is ``None``, never fetched."""
    found, base = urlsplit(url), urlsplit(agent_url)
    if not base.netloc or (found.scheme, found.netloc) != (base.scheme, base.netloc):
        return None
    if found.query or found.fragment:
        return None
    root = f"{base.path.rstrip('/')}/{media_path.strip('/')}/"
    if not found.path.startswith(root):
        return None
    pieces = found.path[len(root) :].split("/")
    if len(pieces) != 2 or any(MEDIA_ID.fullmatch(p) is None for p in pieces):
        return None
    if not task_id or pieces[0] != task_id:
        return None
    return pieces[0], pieces[1]


class MediaCache:
    """``<root>/<task_id>/<media_id><ext>``: directories ``0700``, files ``0600``, written
    to a fresh temporary name with ``O_NOFOLLOW | O_EXCL`` under a directory opened with
    ``O_NOFOLLOW``, then renamed into place. A symlink planted at the directory or the
    file name is refused, never followed."""

    def __init__(self, root: Path | None = None, *, label: str | None = None) -> None:
        self.root = (root or DEFAULT_CACHE_ROOT).expanduser()
        home = str(Path.home())
        default = str(self.root)
        if default.startswith(home + os.sep):
            default = "~" + default[len(home) :]
        self.label = label or default

    def path(self, task_id: str, media_id: str, media_type: str) -> Path:
        for value in (task_id, media_id):
            if MEDIA_ID.fullmatch(value) is None:
                raise MediaCacheError(f"invalid media id {value!r}")
        extension = EXTENSIONS.get(media_type)
        if extension is None:
            raise MediaCacheError(f"media type {media_type!r} is not cached")
        return self.root / task_id / f"{media_id}{extension}"

    def display(self, path: Path) -> str:
        """``~/.cache/tiny-harness/media/9c41…/Qm3x…k2.png``."""
        media_id = path.stem
        return f"{self.label}/{short(path.parent.name)}/{short(media_id)}{path.suffix}"

    def cached(self, task_id: str, media_id: str, media_type: str) -> Path | None:
        path = self.path(task_id, media_id, media_type)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        return path if stat.S_ISREG(info.st_mode) else None

    def write(self, task_id: str, media_id: str, media_type: str, data: bytes) -> Path:
        path = self.path(task_id, media_id, media_type)
        directory = self._directory(task_id)
        try:
            try:
                existing = os.lstat(path.name, dir_fd=directory)
            except FileNotFoundError:
                existing = None
            if existing is not None and not stat.S_ISREG(existing.st_mode):
                raise MediaCacheError(f"{path} is not a regular file; not written")
            temp = f".{path.name}.{secrets.token_hex(8)}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(temp, flags, 0o600, dir_fd=directory)
            try:
                with os.fdopen(descriptor, "wb") as out:
                    out.write(data)
                os.replace(temp, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            except BaseException:
                os.unlink(temp, dir_fd=directory)
                raise
        finally:
            os.close(directory)
        return path

    def _directory(self, task_id: str) -> int:
        """The task's directory, created ``0700``, opened without following a link."""
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            root = os.open(self.root, flags)
        except OSError as exc:
            raise MediaCacheError(f"{self.root} is not a directory; not written") from exc
        try:
            with contextlib.suppress(FileExistsError):
                os.mkdir(task_id, 0o700, dir_fd=root)
            try:
                return os.open(task_id, flags, dir_fd=root)
            except OSError as exc:
                raise MediaCacheError(
                    f"{self.root / task_id} is not a directory; not written"
                ) from exc
        finally:
            os.close(root)


def graphics_image_view() -> ImageView | None:
    """The inline image widget, WHERE ``textual-image`` is installed and the terminal
    answered its kitty-graphics or sixel query. Call it before the app starts: the
    terminal cannot be queried once Textual owns it."""
    try:
        # By name, not a static import: the ``images`` extra is optional, so a type check
        # of an install without it must not need the package.
        renderable = importlib.import_module("textual_image.renderable")
        widgets = importlib.import_module("textual_image.widget")
        inline = cast(Callable[[str], Widget], widgets.Image)
    except ImportError:
        return None
    detected = cast(type, renderable.Image)
    if detected not in (cast(type, renderable.SixelImage), cast(type, renderable.TGPImage)):
        return None  # halfcell or unicode: no real graphics

    def view(path: Path) -> Widget:
        return inline(str(path))

    return view


# --- conversation entries ------------------------------------------------------------------


class MediaLine(Static):
    """One line of a media entry; ``text`` keeps what it shows (tests, the trace). Never
    parsed as markup: names come from users."""

    DEFAULT_CSS = """
    MediaLine { height: auto; }
    MediaLine.you { color: $text; }
    MediaLine.agent { color: $accent; }
    MediaLine.note { color: $text-muted; }
    MediaLine.error { color: $error; }
    """

    def __init__(self, text: str, *, classes: str = "") -> None:
        super().__init__(text, classes=classes, markup=False)
        self.text = text

    def show(self, text: str) -> None:
        self.text = text
        self.update(text)


class MediaEntry(Vertical):
    """An image of the conversation: an optional header (a user's ``[image] …`` line),
    then the image inline, or the line naming where it was saved. ``bind`` gives it the
    stored medium's ids once the server has them."""

    DEFAULT_CSS = """
    MediaEntry { height: auto; margin: 0 0 1 0; }
    MediaEntry .inline { width: 34; height: 12; }
    """

    def __init__(
        self,
        *,
        name: str,
        media_type: str,
        role: str,
        header: str | None = None,
        indent: int = 0,
        width: int | None = None,
        height: int | None = None,
        own: bool = False,
        data: bytes | None = None,
    ) -> None:
        super().__init__()
        self.data = data  # the user's own bytes, so their file is never fetched back
        self.name_text = name or "image"
        self.media_type = media_type
        self.role = role
        self.indent = indent  # columns, as padding: a wrapped line keeps it
        self.width_px = width
        self.height_px = height
        self.own = own  # the user's own file: they have it, no "saved to" line
        self.url = ""
        self.ids: tuple[str, str] | None = None
        self.path: Path | None = None
        self._header = MediaLine(header, classes=role) if header else None

    def compose(self) -> Iterable[Widget]:
        if self._header is not None:
            yield self._header

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.query(MediaLine))

    @property
    def dimensions(self) -> str:
        if self.width_px and self.height_px:
            return f" · {self.width_px}{TIMES}{self.height_px}"
        return ""

    def bind(
        self, url: str, ids: tuple[str, str], *, width: int | None, height: int | None
    ) -> None:
        self.url, self.ids = url, ids
        self.width_px = width or self.width_px
        self.height_px = height or self.height_px

    def show(self, path: Path, cache: MediaCache, image_view: ImageView | None) -> None:
        """Draw the saved file inline, or say where it is."""
        self.path = path
        caption = f"image · {self.name_text}{self.dimensions}"
        if image_view is not None:
            image = image_view(path)
            image.add_class("inline")
            image.styles.margin = (0, 0, 0, self.indent)
            self.mount(image)
            if not self.own:
                self._line(caption, self.role)
            return
        if self.own:
            return
        self._line(f"{caption} · saved to {cache.display(path)}", self.role)
        self._line(NO_GRAPHICS, self.role)

    def unavailable(self, why: str) -> None:
        self._line(f"image · {self.name_text} · unavailable ({why})", "note")

    def _line(self, text: str, role: str) -> None:
        line = MediaLine(text, classes=role)
        line.styles.padding = (0, 0, 0, self.indent)
        self.mount(line)


class AudioEntry(MediaLine):
    """An audio file or a recording: ``[audio] note.wav · 0:12 · ⏎ to play``; a voice
    turn shows its transcript when it arrives. Focus it and press Enter to play it. The
    TUI plays only WAV: another type says ``⏎ saves`` and, once saved, ``saved to
    <path>`` (critic 9)."""

    can_focus = True
    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "play", "play", show=False)]
    DEFAULT_CSS = """
    AudioEntry { margin: 0 0 1 0; }
    AudioEntry:focus { background: $boost; }
    """

    class Play(Message):
        def __init__(self, entry: AudioEntry) -> None:
            super().__init__()
            self.entry = entry

    def __init__(
        self,
        *,
        name: str,
        media_type: str,
        role: str,
        prefix: str = "",
        duration_ms: int | None = None,
        voice: bool = False,
        transcribing: bool = False,
        data: bytes | None = None,
    ) -> None:
        self.prefix = prefix
        self.name_text = name or "audio"
        self.media_type = media_type
        self.duration_ms = duration_ms
        self.voice = voice
        self.transcript: str | None = None
        self.transcribing = transcribing and voice
        self.data = data  # the user's own bytes, so their file is never fetched back
        self.url = ""
        self.ids: tuple[str, str] | None = None
        self.saved_to: str | None = None
        super().__init__(self._line(), classes=role)

    @property
    def hint(self) -> str:
        if self.saved_to is not None:
            return f"saved to {self.saved_to}"
        return PLAY_HINT if self.media_type == PLAYABLE_AUDIO else SAVE_HINT

    def _line(self) -> str:
        duration = f" · {clock(self.duration_ms)}" if self.duration_ms is not None else ""
        if self.voice:
            seconds = f" {clock(self.duration_ms)}" if self.duration_ms is not None else ""
            head = f"{self.prefix}[voice]{seconds}"
            if self.transcript is not None:
                return f"{head} · “{self.transcript}”"
            return f"{head} · transcribing…" if self.transcribing else f"{head} · {self.hint}"
        return f"{self.prefix}[audio] {self.name_text}{duration} · {self.hint}"

    def saved(self, where: str) -> None:
        """Name the cache copy Enter saved (a type the TUI does not play)."""
        self.saved_to = where
        self.show(self._line())

    def bind(self, url: str, ids: tuple[str, str], *, duration_ms: int | None) -> None:
        self.url, self.ids = url, ids
        if duration_ms is not None:
            self.duration_ms = duration_ms
        self.show(self._line())

    def set_transcript(self, text: str) -> None:
        self.transcript = text
        self.show(self._line())

    def action_play(self) -> None:
        self.post_message(self.Play(self))


class SpeechEntry(MediaLine):
    """A spoken reply (R4): ``🔊 speaking ▂▃▅▇▅▃ 0:03 / streaming`` while it plays, then
    spoken, stopped (``Escape``) or interrupted (the stream broke). Enter replays it: the
    URL is requested again and the newest attempt plays from its start."""

    can_focus = True
    BINDINGS: ClassVar[list[BindingType]] = [Binding("enter", "replay", "replay", show=False)]
    DEFAULT_CSS = """
    SpeechEntry { margin: 0 0 1 0; }
    SpeechEntry:focus { background: $boost; }
    """

    class Replay(Message):
        def __init__(self, entry: SpeechEntry) -> None:
            super().__init__()
            self.entry = entry

    def __init__(self, url: str, *, media_id: str, indent: int = 0) -> None:
        self.url = url
        self.media_id = media_id
        self.state = "ready"
        super().__init__("🔊 spoken reply · ⏎ to play", classes="agent")
        self.styles.padding = (0, 0, 0, indent)

    def streaming(self, levels: list[float], played_ms: int) -> None:
        self.state = "streaming"
        self.show(f"🔊 speaking {meter(levels, width=6)} {clock(played_ms)} / streaming")

    def done(self, played_ms: int) -> None:
        self.state = "done"
        self.show(f"🔊 spoken · {clock(played_ms)} · ⏎ replays")

    def stopped(self, played_ms: int) -> None:
        self.state = "stopped"
        self.show(f"🔊 stopped at {clock(played_ms)} · ⏎ replays")

    def interrupted(self) -> None:
        self.state = "interrupted"
        self.show("🔊 speech interrupted · ⏎ replays")

    def unavailable(self, reason: str) -> None:
        self.state = "unavailable"
        self.show(f"🔊 spoken reply · {reason}")

    def action_replay(self) -> None:
        self.post_message(self.Replay(self))


__all__ = [
    "DEFAULT_CACHE_ROOT",
    "EXTENSIONS",
    "MEDIA_ID",
    "NO_GRAPHICS",
    "TIMES",
    "AttachRefused",
    "AudioEntry",
    "ImageView",
    "MediaCache",
    "MediaCacheError",
    "MediaEntry",
    "MediaLine",
    "SpeechEntry",
    "chip_text",
    "clock",
    "complete_path",
    "graphics_image_view",
    "human_size",
    "kind_of",
    "limit_text",
    "load_attachment",
    "media_ids",
    "pinned_media_ids",
    "rejection_text",
]
