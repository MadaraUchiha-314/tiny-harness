"""Media intake and the ingress guard (issue-38 R1.3-R1.5, abuse cases 1-3 and 7, design
critic 5): every file part is checked, stored and rewritten to a media URL before the
message goes on, all or nothing; controls refuse files and remote deliveries drop them."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from a2a.types import Message, Part, Role
from google.protobuf import json_format, struct_pb2

from tests.fixtures import media as fx
from tiny_harness.config import MediaConfig
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore, MediaIntake, MediaKind, MediaRejected, guard
from tiny_harness.jsontypes import JsonObject

BASE = "http://127.0.0.1:8080/agents/a"
TASK = "task-1"


@pytest.fixture
def store(tmp_path: Path) -> FileMediaStore:
    return FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), tmp_path / "media")


@pytest.fixture
def intake(store: FileMediaStore) -> MediaIntake:
    return MediaIntake(store, MediaConfig(), base_url=BASE)


def file_part(
    raw: bytes, media_type: str, filename: str = "", metadata: JsonObject | None = None
) -> Part:
    part = Part(raw=raw, media_type=media_type, filename=filename)
    if metadata:
        part.metadata.update(metadata)
    return part


def message(*parts: Part) -> Message:
    msg = Message(message_id="m1", role=Role.ROLE_USER, parts=list(parts))
    msg.metadata.update({"speak": True})
    return msg


def meta(part: Part) -> JsonObject:
    return json_format.MessageToDict(part.metadata)


def stored(tmp_path: Path) -> list[str]:
    folder = tmp_path / "media" / TASK
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


async def rejected(intake: MediaIntake, msg: Message) -> MediaRejected:
    with pytest.raises(MediaRejected) as caught:
        await intake.extract(msg, task_id=TASK)
    return caught.value


# --- extract --------------------------------------------------------------------------------


async def test_an_image_is_stored_and_rewritten_to_a_media_url(
    intake: MediaIntake, store: FileMediaStore
) -> None:
    raw = fx.png(640, 480)
    msg = message(Part(text="what is this?"), file_part(raw, "image/png", "photo.png"))
    out = await intake.extract(msg, task_id=TASK)
    text, image = out.parts
    assert text.text == "what is this?"
    assert image.WhichOneof("content") == "url"
    data = meta(image)
    media_id = str(data["mediaId"])
    assert image.url == f"{BASE}/media/{TASK}/{media_id}"
    assert (image.media_type, image.filename) == ("image/png", "photo.png")
    assert data == {"mediaId": media_id, "size": len(raw), "width": 640, "height": 480}
    assert json_format.MessageToDict(out.metadata) == {"speak": True}
    assert out.message_id == "m1"
    ref = await store.lookup(TASK, media_id)
    assert ref is not None and ref.kind is MediaKind.IMAGE and ref.name == "photo.png"
    assert await store.get(ref) == raw


async def test_a_recording_keeps_its_voice_flag_and_gains_a_duration(
    intake: MediaIntake, store: FileMediaStore
) -> None:
    raw = fx.webm(duration_ms=None, unknown_sizes=True)
    part = file_part(raw, "audio/webm;codecs=opus", "rec.webm", {"voice": True})
    (audio,) = (await intake.extract(message(part), task_id=TASK)).parts
    data = meta(audio)
    assert audio.media_type == "audio/webm"
    assert data["voice"] is True and data["durationMs"] == 1_020
    ref = await store.lookup(TASK, str(data["mediaId"]))
    assert ref is not None and ref.voice and ref.duration_ms == 1_020


async def test_a_message_without_files_is_unchanged(intake: MediaIntake, tmp_path: Path) -> None:
    value = struct_pb2.Value()
    value.struct_value.update({"a": 1})
    msg = message(Part(text="hi"), Part(data=value, media_type="application/json"))
    assert await intake.extract(msg, task_id=TASK) == msg
    assert stored(tmp_path) == []


async def test_a_message_of_only_files_is_accepted(intake: MediaIntake) -> None:
    out = await intake.extract(message(file_part(fx.wav(0.5), "audio/wav")), task_id=TASK)
    assert [p.WhichOneof("content") for p in out.parts] == ["url"]


# --- refusals, each storing nothing -----------------------------------------------------------


async def test_rejects_url_part(intake: MediaIntake, monkeypatch: pytest.MonkeyPatch) -> None:
    dialled: list[object] = []

    def no_network(*args: object, **kwargs: object) -> None:
        dialled.append(args)
        raise AssertionError("intake must not fetch a URL")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    part = Part(url="http://169.254.169.254/latest/meta-data", media_type="image/png")
    error = await rejected(intake, message(part))
    assert error.reason == "url_not_accepted"
    assert dialled == []


async def test_rejects_oversize_file(store: FileMediaStore, tmp_path: Path) -> None:
    small = MediaIntake(store, MediaConfig(max_file_bytes=1_000), base_url=BASE)
    error = await rejected(small, message(file_part(fx.png(padding=2_000), "image/png", "a.png")))
    assert error.reason == "too_large"
    assert error.detail["limit"] == "1000"
    assert "1000" in error.message and "a.png" in error.message
    assert stored(tmp_path) == []


async def test_rejects_oversize_message(store: FileMediaStore, tmp_path: Path) -> None:
    config = MediaConfig(max_file_bytes=3_000, max_message_bytes=4_000)
    small = MediaIntake(store, config, base_url=BASE)
    each = fx.png(padding=2_000)
    error = await rejected(
        small, message(file_part(each, "image/png"), file_part(each, "image/png"))
    )
    assert error.reason == "message_too_large"
    assert error.detail["limit"] == "4000"
    assert stored(tmp_path) == []


async def test_rejects_svg(intake: MediaIntake) -> None:
    error = await rejected(intake, message(file_part(fx.SVG, "image/svg+xml", "x.svg")))
    assert error.reason == "type_not_accepted"


async def test_rejects_png_declared_as_jpeg(intake: MediaIntake) -> None:
    error = await rejected(intake, message(file_part(fx.png(), "image/jpeg")))
    assert error.reason == "type_mismatch"


async def test_rejects_html_named_png(intake: MediaIntake) -> None:
    error = await rejected(intake, message(file_part(fx.HTML, "image/png", "cat.png")))
    assert error.reason == "type_mismatch"


async def test_rejects_an_unreadable_image_header(intake: MediaIntake) -> None:
    error = await rejected(intake, message(file_part(fx.png()[:20], "image/png")))
    assert error.reason == "type_mismatch"


async def test_rejects_huge_dimensions(intake: MediaIntake, tmp_path: Path) -> None:
    bomb = fx.png(50_000, 50_000, padding=100_000)
    error = await rejected(intake, message(file_part(bomb, "image/png")))
    assert error.reason == "image_too_large"
    assert error.detail["limit"] == "40000000"
    assert stored(tmp_path) == []


@pytest.mark.parametrize(
    ("raw", "media_type", "reason"),
    [
        (fx.mp3_seconds(121), "audio/mpeg", "audio_too_long"),
        (
            fx.mp4(fx.mp4_track(), fx.mp4_track(b"vide", codec=b"avc1")),
            "audio/mp4",
            "not_audio_only",
        ),
        (fx.ogg()[:-5], "audio/ogg", "audio_duration_unknown"),
    ],
)
async def test_rejects_audio_the_checks_refuse(
    intake: MediaIntake, raw: bytes, media_type: str, reason: str
) -> None:
    assert (await rejected(intake, message(file_part(raw, media_type)))).reason == reason


async def test_rejects_a_type_outside_the_effective_set(store: FileMediaStore) -> None:
    images_only = MediaIntake(
        store,
        MediaConfig(),
        base_url=BASE,
        accepted=("image/png", "image/jpeg", "image/webp", "image/gif"),
    )
    error = await rejected(images_only, message(file_part(fx.wav(0.5), "audio/wav")))
    assert error.reason == "type_not_accepted"


async def test_a_later_bad_part_leaves_nothing_stored(intake: MediaIntake, tmp_path: Path) -> None:
    good = file_part(fx.png(), "image/png")
    bad = file_part(fx.HTML, "image/png")
    error = await rejected(intake, message(good, Part(text="and"), bad))
    assert error.reason == "type_mismatch"
    assert error.detail["part"] == "2"
    assert stored(tmp_path) == []


# --- guard ----------------------------------------------------------------------------------


async def test_guard_passes_a_message_without_files_in_every_mode() -> None:
    msg = message(Part(text="hello"))
    for mode in ("extract", "refuse", "drop"):
        assert await guard(msg, allow=mode, task_id=TASK) == msg


async def test_guard_refuses_files_on_a_control() -> None:
    with pytest.raises(MediaRejected) as caught:
        await guard(message(Part(text="done"), file_part(fx.png(), "image/png")), allow="refuse")
    assert caught.value.reason == "files_not_accepted"
    assert "controls carry no files" in caught.value.message


async def test_guard_drops_remote_files_with_a_note() -> None:
    msg = message(
        Part(text="here you go"),
        file_part(fx.png(), "image/png"),
        Part(url="https://remote.example/x.wav", media_type="audio/wav"),
    )
    out = await guard(msg, allow="drop")
    assert [p.WhichOneof("content") for p in out.parts] == ["text", "text", "text"]
    assert [p.text for p in out.parts] == [
        "here you go",
        "[remote agent sent a image/png file; files from remote agents are not supported]",
        "[remote agent sent a audio/wav file; files from remote agents are not supported]",
    ]


async def test_guard_extract_without_media_is_media_off() -> None:
    with pytest.raises(MediaRejected) as caught:
        await guard(message(file_part(fx.png(), "image/png")), allow="extract", task_id=TASK)
    assert caught.value.reason == "media_off"


async def test_guard_extract_refuses_a_url_part_before_media_off() -> None:
    with pytest.raises(MediaRejected) as caught:
        await guard(
            message(Part(url="http://x/y.png", media_type="image/png")),
            allow="extract",
            task_id=TASK,
        )
    assert caught.value.reason == "url_not_accepted"


async def test_guard_extract_with_intake_stores(intake: MediaIntake) -> None:
    out = await guard(
        message(file_part(fx.png(), "image/png")), allow="extract", intake=intake, task_id=TASK
    )
    assert out.parts[0].WhichOneof("content") == "url"
