"""Media models (issue-38 R1.4, R1.5, NFR durability, abuse case 8): the accepted types,
the reference that crosses workflow history, and the attachment that refuses to
serialise once it carries bytes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from tiny_harness.harness.entities import EntityKind
from tiny_harness.harness.media import (
    ACCEPTED,
    PCM_MEDIA_TYPE,
    AudioFormat,
    MediaAttachment,
    MediaKind,
    MediaRef,
)


def ref(**update: object) -> MediaRef:
    fields: dict[str, object] = {
        "id": "Qm3xA1b2C3d4E5f6G7h8I9j0",
        "task_id": "task-1",
        "kind": MediaKind.IMAGE,
        "media_type": "image/png",
        "size": 10,
        "name": "photo.png",
    }
    fields.update(update)
    return MediaRef.model_validate(fields)


def test_accepted_lists_exactly_the_required_types() -> None:
    assert dict(ACCEPTED) == {
        "image/png": MediaKind.IMAGE,
        "image/jpeg": MediaKind.IMAGE,
        "image/webp": MediaKind.IMAGE,
        "image/gif": MediaKind.IMAGE,
        "audio/wav": MediaKind.AUDIO,
        "audio/mpeg": MediaKind.AUDIO,
        "audio/mp4": MediaKind.AUDIO,
        "audio/ogg": MediaKind.AUDIO,
        "audio/webm": MediaKind.AUDIO,
    }
    assert PCM_MEDIA_TYPE not in ACCEPTED


def test_pcm_media_type_matches_the_speech_format() -> None:
    fmt = AudioFormat(encoding="pcm_s16le", sample_rate=24_000, channels=1)
    assert fmt.media_type == PCM_MEDIA_TYPE == "audio/L16;rate=24000;channels=1"


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a.b", "x" * 129, "id with space"])
def test_ids_outside_the_safe_alphabet_are_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        ref(id=bad)
    with pytest.raises(ValidationError):
        ref(task_id=bad)


def test_id_alphabet_admits_token_urlsafe() -> None:
    assert ref(id="a-Z_09" * 4).id == "a-Z_09" * 4


def test_media_type_outside_the_allow_list_is_refused() -> None:
    with pytest.raises(ValidationError):
        ref(media_type="image/svg+xml")


def test_kind_must_match_the_media_type() -> None:
    with pytest.raises(ValidationError):
        ref(kind=MediaKind.AUDIO, media_type="image/png")
    assert ref(kind=MediaKind.AUDIO, media_type=PCM_MEDIA_TYPE).kind is MediaKind.AUDIO


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\photo.png", "photo.png"),
        ("bad\x00name\n.png", "badname.png"),
        ("a" * 300 + ".png", "a" * 120),
    ],
)
def test_name_is_sanitised_to_a_short_basename(given: str, kept: str) -> None:
    assert ref(name=given).name == kept


def test_ref_round_trips_through_json() -> None:
    original = ref(duration_ms=None, width=640, height=480, voice=True)
    assert MediaRef.model_validate_json(original.model_dump_json()) == original


def test_attachment_url_names_the_task_and_media() -> None:
    attachment = MediaAttachment(ref=ref())
    assert (
        attachment.url("http://127.0.0.1:8080/")
        == "http://127.0.0.1:8080/media/task-1/Qm3xA1b2C3d4E5f6G7h8I9j0"
    )


def test_attachment_without_data_serialises() -> None:
    attachment = MediaAttachment(ref=ref(), transcript="hello")
    assert MediaAttachment.model_validate_json(attachment.model_dump_json()) == attachment
    assert "data" not in attachment.model_dump()


def test_attachment_with_data_not_serialisable() -> None:
    attachment = MediaAttachment(ref=ref(), data=b"\x89PNG secret bytes")
    with pytest.raises(PydanticSerializationError, match="media bytes"):
        attachment.model_dump()
    with pytest.raises(PydanticSerializationError, match="media bytes"):
        attachment.model_dump_json()
    assert attachment.data == b"\x89PNG secret bytes"


def test_entity_kinds_gain_the_media_kinds() -> None:
    assert EntityKind.SPEECH_TO_TEXT.value == "speech_to_text"
    assert EntityKind.TEXT_TO_SPEECH.value == "text_to_speech"
    assert EntityKind.IMAGE_GENERATOR.value == "image_generator"
    assert EntityKind.MEDIA_STORE.value == "media_store"
