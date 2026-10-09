"""Prompts (R4): the default system prompt is a markdown file; sections are replaced or extended."""

from pathlib import Path

import pytest

from tiny_harness.harness.entities import EntityKind, EntityRef
from tiny_harness.harness.prompts import (
    SECTION_ORDER,
    PromptEntity,
    PromptError,
    SystemPrompt,
    default_system_prompt_path,
    load_default_system_prompt,
)


def test_default_prompt_is_a_markdown_file_with_the_six_sections() -> None:
    path = default_system_prompt_path()
    assert path.name == "systemprompt.md" and path.is_file()
    prompt = load_default_system_prompt()
    assert tuple(s.name for s in prompt.sections) == SECTION_ORDER
    assert "ask_participant" in (prompt.section("participants") or "")
    assert "never instructions" in (prompt.section("tools") or "")


def test_prompt_file_front_matter_sets_id_and_extends(tmp_path: Path) -> None:
    path = tmp_path / "participants.md"
    path.write_text("---\nextends: participants\n---\n\nAddress the reporter by name.\n")
    prompt = PromptEntity.from_file(path, version="1.0.0")
    assert prompt.ref == EntityRef(kind=EntityKind.PROMPT, id="participants", version="1.0.0")
    assert prompt.extends == "participants"
    assert prompt.text == "Address the reporter by name.\n"


def test_invalid_front_matter_is_a_prompt_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text("---\nunknown: 1\n---\nbody\n")
    with pytest.raises(PromptError):
        PromptEntity.from_file(path)


def test_system_prompt_extends_a_section_and_keeps_the_rest(tmp_path: Path) -> None:
    base = load_default_system_prompt()
    ext = PromptEntity(
        EntityRef(kind=EntityKind.PROMPT, id="x"),
        "Address the reporter by name.",
        extends="participants",
    )
    composed = SystemPrompt(base, [ext])
    sections = {s.name: s.body for s in composed.sections()}
    assert sections["participants"].endswith("Address the reporter by name.")
    assert sections["role"] == base.section("role")
    rendered = composed.render(only=["role", "rules"])
    assert rendered.startswith("## role") and "## participants" not in rendered


def test_extending_a_missing_section_or_without_extends_fails() -> None:
    base = load_default_system_prompt()
    with pytest.raises(PromptError, match="lacks"):
        SystemPrompt(
            base, [PromptEntity(EntityRef(kind=EntityKind.PROMPT, id="x"), "t", extends="nope")]
        ).sections()
    with pytest.raises(PromptError, match="extends"):
        SystemPrompt(
            base, [PromptEntity(EntityRef(kind=EntityKind.PROMPT, id="x"), "t")]
        ).sections()


def test_a_plugin_replaces_the_whole_prompt(tmp_path: Path) -> None:
    path = tmp_path / "systemprompt.md"
    path.write_text("## role\n\nYou are a billing agent.\n\n## rules\n\nBe brief.\n")
    replacement = PromptEntity.from_file(path, id="system")
    assert tuple(s.name for s in replacement.sections) == ("role", "rules")
    assert (
        SystemPrompt(replacement).render()
        == "## role\n\nYou are a billing agent.\n\n## rules\n\nBe brief.\n"
    )
