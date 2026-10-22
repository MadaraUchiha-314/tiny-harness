"""Helpers for the media workflow scenarios (issue-38 T2): a worker over fakes with a file
media store, and a message whose files went through media intake as the executor does."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

from a2a.types import Message, Part
from a2a.types import Role as A2ARole

from tests.integration.durable.conftest import Harness
from tiny_harness.config import MediaConfig
from tiny_harness.harness.core import (
    HarnessTask,
    Participant,
    Role,
    SubState,
    TaskExtensionData,
)
from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.media import FileMediaStore, MediaIntake
from tiny_harness.harness.models import LLMResponse, Modality, SpeechToText, TextToSpeech
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.durable.models import EventEntry

BASE_URL = "http://harness"


def ids() -> tuple[str, str]:
    """A fresh task queue and task id."""
    suffix = uuid.uuid4().hex[:8]
    return f"tq-{suffix}", f"t-{suffix}"


def media_task(task_id: str, *, participants: Sequence[str] = ("alice",)) -> HarnessTask:
    people = tuple(Participant(id=p, kind="human", role=Role.REPORTER) for p in participants)
    return HarnessTask.new(
        task_id,
        "ctx-1",
        TaskExtensionData(
            name="Media",
            goal="Talk about media",
            participants=(*people, Participant(id="agent", kind="agent", role=Role.ASSIGNEE)),
        ),
    )


async def media_harness(
    root: Path,
    responses: Sequence[LLMResponse],
    *,
    modalities: frozenset[Modality] = frozenset({"text", "image"}),
    audio_formats: frozenset[str] = frozenset(),
    stt: SpeechToText | None = None,
    tts: TextToSpeech | None = None,
) -> tuple[Harness, FileMediaStore]:
    store = FileMediaStore(EntityRef(kind=EntityKind.MEDIA_STORE, id="file"), root)
    h = Harness(responses, media_store=store, speech_to_text=stt, text_to_speech=tts)
    h.llm.info = h.llm.info.model_copy(
        update={"input_modalities": modalities, "audio_input_formats": audio_formats}
    )
    return await h.bind(), store


async def with_files(
    store: FileMediaStore,
    task_id: str,
    text: str,
    files: Sequence[tuple[bytes, str, str]],
    *,
    message_id: str,
    participant: str = "alice",
    voice: bool = False,
    speak: bool = False,
) -> Message:
    """A message with ``files`` (bytes, media type, name), extracted by ``MediaIntake`` as
    the executor does before the message enters the workflow."""
    parts = [Part(text=text)] if text else []
    for raw, media_type, name in files:
        part = Part(raw=raw, media_type=media_type, filename=name)
        if voice:
            part.metadata.update({"voice": True})
        parts.append(part)
    msg = Message(
        message_id=message_id,
        context_id="ctx-1",
        task_id=task_id,
        role=A2ARole.ROLE_USER,
        parts=parts,
    )
    msg.metadata.update({"participant_id": participant})
    if speak:
        msg.metadata.update({"speak": True})
    intake = MediaIntake(store, MediaConfig(), base_url=BASE_URL)
    return await intake.extract(msg, task_id=task_id)


def artifacts(events: Sequence[EventEntry], prefix: str) -> list[JsonObject]:
    """The artifacts of the artifact updates whose id starts with ``prefix``, in order."""
    found: list[JsonObject] = []
    for entry in events:
        if entry.kind != "artifact_update":
            continue
        artifact = entry.payload.get("artifact")
        if isinstance(artifact, dict) and str(artifact.get("artifactId", "")).startswith(prefix):
            found.append(artifact)
    return found


def replied(text: str) -> Callable[[HarnessTask], bool]:
    """The task parked awaiting the next message with ``text`` as its status message."""

    def check(task: HarnessTask) -> bool:
        parts = task.proto.status.message.parts
        return (
            task.sub_state is SubState.AWAITING_NEXT_MESSAGE
            and bool(parts)
            and parts[0].text == text
        )

    return check


def parts_of(artifact: JsonObject) -> list[JsonObject]:
    """An artifact's parts, as ProtoJSON objects."""
    parts = artifact.get("parts")
    return [p for p in parts if isinstance(p, dict)] if isinstance(parts, list) else []


def status_texts(events: Sequence[EventEntry]) -> list[str]:
    """The text of every status update's message, in order."""
    texts: list[str] = []
    for entry in events:
        if entry.kind != "status_update":
            continue
        status = entry.payload.get("status")
        message = status.get("message") if isinstance(status, dict) else None
        parts = message.get("parts") if isinstance(message, dict) else None
        if isinstance(parts, list):
            texts += [str(p["text"]) for p in parts if isinstance(p, dict) and "text" in p]
    return texts


__all__ = [
    "BASE_URL",
    "artifacts",
    "ids",
    "media_harness",
    "media_task",
    "parts_of",
    "replied",
    "status_texts",
    "with_files",
]
