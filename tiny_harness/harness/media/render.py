"""Media as model content (issue-38 R1.6): what the adapters share.

An adapter sends an attachment's bytes only once an activity has resolved them; one that
reaches an adapter unresolved is a programming error, raised as ``ProviderError`` rather
than dropped. Audio with a transcript is sent as text, labelled with its file name.
"""

from __future__ import annotations

import base64
import math
import re
from typing import TYPE_CHECKING, Final

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


SPEECH_INPUT_LIMIT: Final = 4_096
"""The most text one text-to-speech call takes (OpenAI's input limit); the rest of a longer
reply is left to its text."""

_FENCED: Final = re.compile(r"^\s*(```|~~~).*?^\s*\1[^\n]*$", re.MULTILINE | re.DOTALL)
_IMAGE: Final = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK: Final = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HTML: Final = re.compile(r"<[^>\n]+>")
_INLINE_CODE: Final = re.compile(r"`([^`]*)`")
_EMPHASIS: Final = re.compile(r"(\*\*|__|~~|\*)(?=\S)(.+?)(?<=\S)\1")
_BLOCK_MARK: Final = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)")
_RULE: Final = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_TABLE_RULE: Final = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")


def speakable_text(text: str, *, limit: int = SPEECH_INPUT_LIMIT) -> str:
    """``text`` as text-to-speech should read it (issue-38 R4.1): code blocks dropped,
    markdown marks, links' targets and HTML tags removed, table cells joined by spaces,
    blank lines dropped; at most ``limit`` characters, cut at a word where one is near."""
    text = _FENCED.sub("", text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _HTML.sub(" ", text)
    text = _INLINE_CODE.sub(r"\1", text)
    lines: list[str] = []
    for raw in text.splitlines():
        if _RULE.match(raw) or _TABLE_RULE.match(raw):
            continue
        line = _BLOCK_MARK.sub("", raw)
        line = _EMPHASIS.sub(r"\2", line)
        line = " ".join(line.replace("|", " ").split())
        if line:
            lines.append(line)
    spoken = "\n".join(lines)
    if len(spoken) <= limit:
        return spoken
    cut = spoken[:limit]
    at = max(cut.rfind(" "), cut.rfind("\n"))
    return cut[:at].rstrip() if at > limit // 2 else cut


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


def not_resent(attachment: MediaAttachment) -> str:
    """What a model reads in place of older media that the request's budget leaves out."""
    return f"[{attachment.ref.kind.value} {label(attachment)} shown earlier, not re-sent]"


def over_request_limit(attachment: MediaAttachment) -> str:
    """What a model reads in place of new media that does not fit the request's budget."""
    kind = attachment.ref.kind.value
    return f"[{kind} {label(attachment)} not sent: over the request's media limit]"


def too_large(attachment: MediaAttachment) -> str:
    """What a model reads in place of an image larger than its adapter's API takes."""
    return f"[image {label(attachment)} too large for this model]"


def _base64_size(size: int) -> int:
    return 4 * math.ceil(size / 3)


async def resolve_media(
    request: LLMRequest,
    store: MediaStore | None,
    info: LLMModelInfo,
    *,
    max_bytes: int | None = None,
) -> LLMRequest:
    """``request`` with each attachment ready for the adapter (issue-38 R1.6, R1.7): an
    image's bytes WHERE the model takes images; native audio's bytes WHERE the model takes
    that audio type; transcribed audio as it is (the adapter sends the transcript). Media
    the model cannot take becomes a line of text in its message. Runs only inside an
    activity: the result holds bytes and cannot be serialised (abuse case 8). Without a
    store the request is returned as it is, and an adapter refuses unresolved media.

    The bytes of one request stay within ``max_bytes`` (``[media]
    max_request_media_bytes``; self-review 2.1): the newest media is resolved first, and
    older media that does not fit becomes a line of text. An image larger than the
    adapter's ``max_image_bytes`` (as base64) is never sent."""
    if store is None or not any(item.kind == "message" and item.media for item in request.input):
        return request
    images = "image" in info.input_modalities
    audio = "audio" in info.input_modalities
    last = max(i for i, item in enumerate(request.input) if item.kind == "message")
    remaining = max_bytes
    # Decide newest first, so the budget goes to the newest media; build in order after.
    decided: dict[tuple[int, int], MediaAttachment | str] = {}
    for i in range(len(request.input) - 1, -1, -1):
        item = request.input[i]
        if item.kind != "message" or not item.media:
            continue
        left_out = over_request_limit if i == last else not_resent
        for j in range(len(item.media) - 1, -1, -1):
            attachment = item.media[j]
            ref = attachment.ref
            needs_bytes = (images and ref.kind is MediaKind.IMAGE) or (
                ref.kind is MediaKind.AUDIO
                and attachment.transcript is None
                and audio
                and ref.media_type in info.audio_input_formats
            )
            if ref.kind is MediaKind.IMAGE and not images:
                decided[i, j] = image_not_shown(attachment)
            elif ref.kind is MediaKind.AUDIO and attachment.transcript is not None:
                decided[i, j] = attachment
            elif not needs_bytes:
                decided[i, j] = audio_not_given(attachment)
            elif (
                ref.kind is MediaKind.IMAGE
                and info.max_image_bytes is not None
                and _base64_size(ref.size) > info.max_image_bytes
            ):
                decided[i, j] = too_large(attachment)
            elif remaining is not None and ref.size > remaining:
                decided[i, j] = (
                    over_request_limit(attachment) if i == last else not_resent(attachment)
                )
            else:
                try:
                    data = await store.get(ref)
                except FileNotFoundError:
                    decided[i, j] = unavailable(attachment)
                    continue
                if remaining is not None:
                    if len(data) > remaining:
                        decided[i, j] = left_out(attachment)
                        continue
                    remaining -= len(data)
                decided[i, j] = MediaAttachment(
                    ref=ref, transcript=attachment.transcript, data=data
                )
    items: list[InputItem] = []
    for i, item in enumerate(request.input):
        if item.kind != "message" or not item.media:
            items.append(item)
            continue
        kept: list[MediaAttachment] = []
        notes: list[str] = []
        for j in range(len(item.media)):
            outcome = decided[i, j]
            if isinstance(outcome, str):
                notes.append(outcome)
            else:
                kept.append(outcome)
        text = "\n".join([item.text, *notes]) if item.text else "\n".join(notes)
        items.append(item.model_copy(update={"media": tuple(kept), "text": text}))
    return request.model_copy(update={"input": tuple(items)})


__all__ = [
    "SPEECH_INPUT_LIMIT",
    "audio_not_given",
    "base64_data",
    "data_url",
    "image_not_shown",
    "label",
    "not_resent",
    "over_request_limit",
    "resolve_media",
    "resolved",
    "speakable_text",
    "too_large",
    "transcript_text",
    "unavailable",
    "unseen_images",
]
