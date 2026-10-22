"""Feature: The multi-modal demo
Requirement: docs/specs/issue-38/requirements.md#R7.1

``examples/multimodal`` offline: its config turns every media service on with OpenAI and an
embedded Temporal, its plugin loads with the interior-design prompt, its banner says how to
reach both surfaces, and the media intake accepts each fixture as it is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from examples.multimodal.__main__ import CONFIG, FIXTURES, banner
from tiny_harness.config import MediaConfig, Settings
from tiny_harness.harness.media import sniff
from tiny_harness.harness.plugins.loader import discover

ENV = {"OPENAI_API_KEY": "sk-secret"}
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "multimodal"


def test_the_config_turns_every_media_service_on_with_openai_and_embedded_temporal() -> None:
    """
    Feature: The multi-modal demo
    Requirement: docs/specs/issue-38/requirements.md#R7.1

    Scenario: the demo's config needs only OPENAI_API_KEY
        Given examples/multimodal/config.toml and only OPENAI_API_KEY in the environment
        When it is loaded
        Then Temporal is embedded and the server binds 127.0.0.1:8080 with the web renderer
        And media, speech-to-text, text-to-speech and image generation use the named OpenAI models
    """
    settings = Settings.load(CONFIG, env=ENV)
    assert settings.temporal.mode == "embedded"
    assert settings.server.bind == "127.0.0.1:8080"
    assert settings.server.ui_dir is not None
    assert settings.openai.model == "gpt-6.1-sol"
    assert settings.media is not None
    assert settings.speech_to_text is not None
    assert settings.speech_to_text.model == "gpt-4o-mini-transcribe"
    assert settings.text_to_speech is not None
    assert (settings.text_to_speech.model, settings.text_to_speech.voice) == (
        "gpt-4o-mini-tts",
        "coral",
    )
    assert settings.image_generation is not None
    assert settings.image_generation.model == "gpt-image-2"


def test_the_banner_names_the_web_renderer_the_tui_and_the_extras() -> None:
    """
    Feature: The multi-modal demo
    Requirement: docs/specs/issue-38/requirements.md#R7.1

    Scenario: the demo prints how to start both surfaces
        Given the demo's settings
        When the banner is printed
        Then it names the web renderer at /ui, the TUI command and the voice and images extras
    """
    text = banner(Settings.load(CONFIG, env=ENV))
    assert "http://127.0.0.1:8080/ui/" in text
    assert "tiny-harness tui --url http://127.0.0.1:8080" in text
    assert "tiny-harness[voice,images]" in text
    assert str(FIXTURES / "room.jpg") in text


def test_the_plugin_loads_the_interior_design_prompt() -> None:
    """
    Feature: The multi-modal demo
    Requirement: docs/specs/issue-38/requirements.md#R7.1

    Scenario: the plugin makes the agent an interior design helper
        Given examples/multimodal as a plugin directory
        When it is discovered
        Then it loads without notes and its prompt extension tells the agent to call generate_image
    """
    plugin = discover(EXAMPLE)
    assert plugin.notes == ()
    [prompt] = plugin.prompts
    text = prompt.read_text()
    assert "interior design helper" in text
    assert "`generate_image`" in text


@pytest.mark.parametrize(
    ("name", "media_type"),
    [("room.jpg", "image/jpeg"), ("question.wav", "audio/wav"), ("followup.wav", "audio/wav")],
)
def test_each_fixture_passes_the_media_checks(name: str, media_type: str) -> None:
    """
    Feature: The multi-modal demo
    Requirement: docs/specs/issue-38/requirements.md#R7.3

    Scenario: the committed fixtures are what the intake accepts
        Given a fixture of the demo
        Then its signature matches its type and it is within the default media limits
        And it is small enough to keep in the repository
    """
    raw = (FIXTURES / name).read_bytes()
    limits = MediaConfig()
    assert sniff.detect(raw) == media_type
    assert len(raw) <= 300 * 1024
    if media_type.startswith("image/"):
        width, height = sniff.image_size(raw)
        assert width * height <= limits.max_image_pixels
    else:
        info = sniff.audio_info(raw, media_type, max_seconds=limits.max_audio_seconds)
        assert 0 < info.duration_ms <= limits.max_audio_seconds * 1000
