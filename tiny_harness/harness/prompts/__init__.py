"""Prompt entities and the default system prompt stored as markdown (R4)."""

from pathlib import Path

from tiny_harness.harness.prompts.entity import (
    SECTION_ORDER,
    SYSTEM_PROMPT_ID,
    PromptEntity,
    PromptError,
    PromptFrontMatter,
    PromptSection,
    SystemPrompt,
    parse_sections,
    split_front_matter,
)

BUILTIN_NAMESPACE_DIR = (
    Path(__file__).resolve().parents[2] / "builtin" / "io.github.madarauchiha-314.tiny-harness"
)


def default_system_prompt_path() -> Path:
    """The markdown file the default system prompt ships as (R4.4)."""
    return BUILTIN_NAMESPACE_DIR / "systemprompt.md"


def load_default_system_prompt() -> PromptEntity:
    return PromptEntity.from_file(default_system_prompt_path(), id=SYSTEM_PROMPT_ID)


__all__ = [
    "BUILTIN_NAMESPACE_DIR",
    "SECTION_ORDER",
    "SYSTEM_PROMPT_ID",
    "PromptEntity",
    "PromptError",
    "PromptFrontMatter",
    "PromptSection",
    "SystemPrompt",
    "default_system_prompt_path",
    "load_default_system_prompt",
    "parse_sections",
    "split_front_matter",
]
