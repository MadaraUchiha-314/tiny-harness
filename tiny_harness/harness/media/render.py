"""Media as model content (issue-38 R1.6): what the adapters share.

An adapter sends an attachment's bytes only once an activity has resolved them; one that
reaches an adapter unresolved is a programming error, raised as ``ProviderError`` rather
than dropped. Audio with a transcript is sent as text, labelled with its file name.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from tiny_harness.errors import ProviderError
from tiny_harness.harness.media.models import MediaAttachment, MediaKind, MediaRef

if TYPE_CHECKING:
    from tiny_harness.harness.media.store import MediaStore
    from tiny_harness.harness.models.llm import InputItem, LLMModelInfo, LLMRequest


def label(attachment: MediaAttachment) -> str:
    """The name a model and a summary see: the file name, else the media id."""
    return attachment.ref.name or attachment.ref.id


def resolved(attachment: MediaAttachment, *, provider: str) -> bytes:
    """The attachment's bytes; ``ProviderError`` when they were never resolved."""
    if attachment.data is None:
        raise ProviderError(
            "media not resolved", provider=provider, status=0, media=attachment.ref.id
        )
    return attachment.data


def base64_data(attachment: MediaAttachment, *, provider: str) -> str:
    return base64.b64encode(resolved(attachment, provider=provider)).decode("ascii")


def data_url(attachment: MediaAttachment, *, provider: str) -> str:
    """``data:<type>;base64,…`` of a resolved attachment."""
    return f"data:{attachment.ref.media_type};base64,{base64_data(attachment, provider=provider)}"


def transcript_text(attachment: MediaAttachment) -> str | None:
    """``[transcript of <name>] …`` when the attachment has a transcript."""
    if attachment.transcript is None:
        return None
    return f"[transcript of {label(attachment)}] {attachment.transcript}"


def image_not_shown(attachment: MediaAttachment) -> str:
    """What a model that takes no image input reads in place of an image (R1.7)."""
    return f"[image {label(attachment)} not shown: the model takes no image input]"


def audio_not_given(attachment: MediaAttachment) -> str:
    """What a model reads in place of audio it cannot take and that has no transcript."""
    return f"[audio {label(attachment)} not given to the model: no transcript]"


def unavailable(attachment: MediaAttachment) -> str:
    """What a model reads in place of media no longer in the store (retention)."""
    return f"[{attachment.ref.kind.value} {label(attachment)} is no longer available]"


def unseen_images(request: LLMRequest, info: LLMModelInfo) -> tuple[MediaRef, ...]:
    """The images of ``request`` that a model with ``info`` cannot be shown (R1.7)."""
    if "image" in info.input_modalities:
        return ()
    return tuple(
        attachment.ref
        for item in request.input
        if item.kind == "message"
        for attachment in item.media
        if attachment.ref.kind is MediaKind.IMAGE
    )


async def resolve_media(
    request: LLMRequest, store: MediaStore | None, info: LLMModelInfo
) -> LLMRequest:
    """``request`` with each attachment ready for the adapter (issue-38 R1.6, R1.7): an
    image's bytes WHERE the model takes images; native audio's bytes WHERE the model takes
    that audio type; transcribed audio as it is (the adapter sends the transcript). Media
    the model cannot take becomes a line of text in its message. Runs only inside an
    activity: the result holds bytes and cannot be serialised (abuse case 8). Without a
    store the request is returned as it is, and an adapter refuses unresolved media."""
    if store is None or not any(item.kind == "message" and item.media for item in request.input):
        return request
    images = "image" in info.input_modalities
    audio = "audio" in info.input_modalities
    items: list[InputItem] = []
    for item in request.input:
        if item.kind != "message" or not item.media:
            items.append(item)
            continue
        kept: list[MediaAttachment] = []
        notes: list[str] = []
        for attachment in item.media:
            ref = attachment.ref
            needs_bytes = (images and ref.kind is MediaKind.IMAGE) or (
                ref.kind is MediaKind.AUDIO
                and attachment.transcript is None
                and audio
                and ref.media_type in info.audio_input_formats
            )
            if ref.kind is MediaKind.IMAGE and not images:
                notes.append(image_not_shown(attachment))
            elif ref.kind is MediaKind.AUDIO and attachment.transcript is not None:
                kept.append(attachment)
            elif not needs_bytes:
                notes.append(audio_not_given(attachment))
            else:
                try:
                    data = await store.get(ref)
                except FileNotFoundError:
                    notes.append(unavailable(attachment))
                    continue
                kept.append(MediaAttachment(ref=ref, transcript=attachment.transcript, data=data))
        text = "\n".join([item.text, *notes]) if item.text else "\n".join(notes)
        items.append(item.model_copy(update={"media": tuple(kept), "text": text}))
    return request.model_copy(update={"input": tuple(items)})


__all__ = [
    "audio_not_given",
    "base64_data",
    "data_url",
    "image_not_shown",
    "label",
    "resolve_media",
    "resolved",
    "transcript_text",
    "unavailable",
    "unseen_images",
]
