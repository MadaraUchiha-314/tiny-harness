"""T1 (issue-38 R2.3, R2.4, R5.6): a renderer turns a ``url`` file part of an accepted
media type, or of the spoken-reply PCM type, into a ``media`` item with its URL, file
name and part metadata; anything else stays a placeholder (R20.4)."""

from __future__ import annotations

from a2a.types import Artifact, Message, Part, Role, TaskArtifactUpdateEvent

from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import ACCEPTED, PCM_MEDIA_TYPE
from tiny_harness.interaction.renderer import (
    TEXT_PLAIN,
    Renderer,
    RenderItem,
    RenderPlan,
    plan_message,
)
from tiny_harness.interaction.surface import Modality

URL = "http://127.0.0.1:8080/media/t-1/Qm3xk2"
SUPPORTED = frozenset({TEXT_PLAIN, *ACCEPTED, PCM_MEDIA_TYPE})


def url_part(media_type: str, *, name: str = "", **metadata: str | int | bool) -> Part:
    part = Part(url=URL, media_type=media_type, filename=name)
    if metadata:
        part.metadata.update(metadata)
    return part


def user(*parts: Part) -> Message:
    return Message(message_id="m-1", role=Role.ROLE_USER, parts=list(parts))


class Recording(Renderer):
    def render(self, plan: RenderPlan) -> None:
        return None


def test_modalities_include_image_and_audio() -> None:
    assert {m.value for m in Modality} == {"text", "image", "audio"}


def test_an_accepted_url_part_is_a_media_item() -> None:
    meta = {"mediaId": "Qm3xk2", "size": 940, "width": 1024, "height": 768}
    items = plan_message(
        user(Part(text="Which works?"), url_part("image/jpeg", name="sofa.jpg", **meta)),
        SUPPORTED,
    )
    assert items[0] == RenderItem(kind="text", text="Which works?", role="user")
    media = items[1]
    assert media.kind == "media" and media.role == "user"
    assert media.media_type == "image/jpeg"
    assert media.url == URL and media.name == "sofa.jpg"
    assert media.data == meta


def test_a_voice_recording_keeps_its_part_metadata() -> None:
    [item] = plan_message(
        user(url_part("audio/wav", name="voice.wav", mediaId="a1", durationMs=4000, voice=True)),
        SUPPORTED,
    )
    assert item.kind == "media" and item.data is not None
    assert item.data["voice"] is True and item.data["durationMs"] == 4000


def test_a_spoken_reply_is_a_media_item() -> None:
    renderer = Recording(EntityRef(kind=EntityKind.RENDERER, id="r"), supported=sorted(SUPPORTED))
    event = TaskArtifactUpdateEvent(
        task_id="t-1",
        artifact=Artifact(artifact_id="speech:s1", name="speech", parts=[url_part(PCM_MEDIA_TYPE)]),
    )
    [item] = renderer.plan(event).items
    assert item.kind == "media" and item.media_type == PCM_MEDIA_TYPE and item.url == URL


def test_an_agent_image_artifact_is_a_media_item_named_by_its_part() -> None:
    renderer = Recording(EntityRef(kind=EntityKind.RENDERER, id="r"), supported=sorted(SUPPORTED))
    event = TaskArtifactUpdateEvent(
        task_id="t-1",
        artifact=Artifact(
            artifact_id="image:i1",
            name="a green sofa",
            parts=[url_part("image/png", name="generated.png", mediaId="i1")],
        ),
    )
    [item] = renderer.plan(event).items
    assert item.kind == "media" and item.role == "agent" and item.name == "generated.png"


def test_types_outside_the_allow_list_stay_placeholders() -> None:
    """SVG and HTML are never media items (abuse case 6), nor is a raw part, nor a type the
    renderer does not draw."""
    items = plan_message(
        user(
            url_part("image/svg+xml"),
            url_part("text/html"),
            Part(raw=b"\x89PNG", media_type="image/png"),
        ),
        SUPPORTED,
    )
    assert [i.kind for i in items] == ["placeholder"] * 3
    [text_only] = plan_message(user(url_part("image/png")), frozenset({TEXT_PLAIN}))
    assert text_only.kind == "placeholder" and text_only.text == "[unrenderable part: image/png]"
