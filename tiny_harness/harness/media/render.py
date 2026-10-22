"""Media as model content (issue-38 R1.6): what the adapters share.

An adapter sends an attachment's bytes only once an activity has resolved them; one that
reaches an adapter unresolved is a programming error, raised as ``ProviderError`` rather
than dropped. Audio with a transcript is sent as text, labelled with its file name.
"""

from __future__ import annotations

import base64

from tiny_harness.errors import ProviderError
from tiny_harness.harness.media.models import MediaAttachment


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


__all__ = ["base64_data", "data_url", "label", "resolved", "transcript_text"]
