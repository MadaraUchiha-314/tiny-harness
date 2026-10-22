"""The instance's effective media capabilities (issue-38 R5.5, design critic 9).

``capabilities`` is computed once at start from the model, the speech and image entities
and ``[media]``; the agent card, the intake's allow-list and the surfaces all read that one
value, so nothing is advertised or accepted that the instance cannot process:

- input images: every accepted image type, always (R1.7: an image the model cannot see is
  accepted and noted, and ``/model`` may switch to one that can);
- input audio: every accepted audio type with speech-to-text; else the model's native
  ``audio_input_formats`` when it takes ``audio``; else none;
- output: ``image/png`` with an image generator, the PCM speech type with text-to-speech.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from tiny_harness.harness.media.models import ACCEPTED, PCM_MEDIA_TYPE, MediaKind

if TYPE_CHECKING:
    from tiny_harness.config import MediaConfig
    from tiny_harness.harness.models.images import ImageGenerator
    from tiny_harness.harness.models.llm import LLMModelInfo
    from tiny_harness.harness.models.speech import SpeechToText, TextToSpeech

GENERATED_IMAGE_TYPE = "image/png"


class MediaCapabilities(BaseModel, frozen=True):
    """What the instance accepts and produces. The default is a text-only instance."""

    enabled: bool = False
    input: tuple[str, ...] = ()
    output: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ("text",)
    speech_to_text: bool = False
    text_to_speech: bool = False
    image_generation: bool = False
    max_file_bytes: int = 0
    max_message_bytes: int = 0
    max_audio_seconds: int = 0


def capabilities(
    model_info: LLMModelInfo,
    stt: SpeechToText | None,
    tts: TextToSpeech | None,
    image_generator: ImageGenerator | None,
    config: MediaConfig | None,
) -> MediaCapabilities:
    """The effective capabilities; ``config`` ``None`` (no ``[media]``) is text-only."""
    if config is None:
        return MediaCapabilities()
    images = [t for t, kind in ACCEPTED.items() if kind is MediaKind.IMAGE]
    if stt is not None:
        audio = [t for t, kind in ACCEPTED.items() if kind is MediaKind.AUDIO]
    elif "audio" in model_info.input_modalities:
        audio = [
            t
            for t, kind in ACCEPTED.items()
            if kind is MediaKind.AUDIO and t in model_info.audio_input_formats
        ]
    else:
        audio = []
    output: list[str] = []
    if image_generator is not None:
        output.append(GENERATED_IMAGE_TYPE)
    if tts is not None:
        output.append(PCM_MEDIA_TYPE)
    return MediaCapabilities(
        enabled=True,
        input=(*images, *audio),
        output=tuple(output),
        output_modalities=tuple(sorted(model_info.output_modalities)),
        speech_to_text=stt is not None,
        text_to_speech=tts is not None,
        image_generation=image_generator is not None,
        max_file_bytes=config.max_file_bytes,
        max_message_bytes=config.max_message_bytes,
        max_audio_seconds=config.max_audio_seconds,
    )


__all__ = ["GENERATED_IMAGE_TYPE", "MediaCapabilities", "capabilities"]
