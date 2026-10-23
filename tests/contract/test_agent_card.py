"""T6: the agent card is pinned; every extension the harness declares is in it (R14.2)."""

from __future__ import annotations

import json
import os

import jsonschema
from google.protobuf import json_format

from tests.contract._api import SNAPSHOTS
from tiny_harness.harness.commands import BUILTIN_SPECS
from tiny_harness.harness.media import ACCEPTED, PCM_MEDIA_TYPE, MediaCapabilities, MediaKind
from tiny_harness.harness.media.extension import MEDIA_EXT_URI, media_extension_schema
from tiny_harness.interaction.a2ui import A2UI_EXT_URI, BASIC_CATALOG_ID
from tiny_harness.service.a2a.card import AgentDescription, build_agent_card


def test_agent_card_snapshot() -> None:
    card = build_agent_card(AgentDescription(), "http://127.0.0.1:8080", commands=BUILTIN_SPECS)
    rendered = json.dumps(json_format.MessageToDict(card), indent=2, sort_keys=True) + "\n"
    path = SNAPSHOTS / "agent-card.json"
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(rendered)
    assert rendered == path.read_text(), (
        "agent card changed; review and rerun with UPDATE_API_SNAPSHOTS=1"
    )
    a2ui = next(e for e in card.capabilities.extensions if e.uri == A2UI_EXT_URI)
    params = json_format.MessageToDict(a2ui.params)
    assert params == {"supportedCatalogIds": [BASIC_CATALOG_ID], "acceptsInlineCatalogs": False}


MEDIA = MediaCapabilities(
    enabled=True,
    input=(*(t for t, k in ACCEPTED.items() if k is MediaKind.IMAGE), "audio/wav", "audio/webm"),
    output=("image/png", PCM_MEDIA_TYPE),
    speech_to_text=True,
    text_to_speech=True,
    image_generation=True,
    max_file_bytes=20_971_520,
    max_message_bytes=26_214_400,
    max_audio_seconds=120,
)


def test_the_card_is_unchanged_without_media() -> None:
    """T3/T10 (issue-38): no [media] gives exactly the pinned 0.8.0 card."""
    plain = build_agent_card(AgentDescription(), "http://127.0.0.1:8080", commands=BUILTIN_SPECS)
    off = build_agent_card(
        AgentDescription(),
        "http://127.0.0.1:8080",
        commands=BUILTIN_SPECS,
        media=MediaCapabilities(),
    )
    assert off == plain
    assert MEDIA_EXT_URI not in {e.uri for e in off.capabilities.extensions}


def test_agent_card_with_media_snapshot() -> None:
    """T3 (issue-38 R5.5, R5.6): with [media] the card lists the effective input and output
    types and declares the media extension, whose params the published schema validates."""
    card = build_agent_card(
        AgentDescription(), "http://127.0.0.1:8080", commands=BUILTIN_SPECS, media=MEDIA
    )
    rendered = json.dumps(json_format.MessageToDict(card), indent=2, sort_keys=True) + "\n"
    path = SNAPSHOTS / "agent-card-media.json"
    if os.environ.get("UPDATE_API_SNAPSHOTS") == "1" or not path.exists():
        path.write_text(rendered)
    assert rendered == path.read_text(), (
        "agent card with media changed; review and rerun with UPDATE_API_SNAPSHOTS=1"
    )
    assert set(MEDIA.input) <= set(card.default_input_modes)
    assert set(MEDIA.output) <= set(card.default_output_modes)
    assert PCM_MEDIA_TYPE not in card.default_input_modes
    media = next(e for e in card.capabilities.extensions if e.uri == MEDIA_EXT_URI)
    assert media.required is False
    params = json_format.MessageToDict(media.params)
    jsonschema.validate(params, media_extension_schema())
    assert params == {
        "input": list(MEDIA.input),
        "output": ["image/png", PCM_MEDIA_TYPE],
        "maxFileBytes": 20_971_520,
        "maxMessageBytes": 26_214_400,
        "maxAudioSeconds": 120,
        "speechToText": True,
        "textToSpeech": True,
        "imageGeneration": True,
        "mediaPath": "/media",
    }
