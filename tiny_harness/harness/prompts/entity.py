"""Prompt entities and the system prompt (R4).

The default system prompt is a markdown file shipped with the package (4.4), the
built-in plugin's ``io.github.madarauchiha-314.tiny-harness/systemprompt.md``, parsed
into named sections by its ``##`` headings: ``role``, ``task``, ``participants``,
``tools``, ``skills``, ``rules``. A plugin replaces the whole file (``systemprompt.md``
in its namespace directory) or extends one section with a prompt file whose front
matter says ``extends: <section>`` (4.2). The context window manager renders the stable
sections first (4.3, 10.3).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel, ValidationError

from tiny_harness.errors import TinyHarnessError
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef

SYSTEM_PROMPT_ID = "system"
SECTION_ORDER: tuple[str, ...] = ("role", "task", "participants", "tools", "skills", "rules")
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_HEADING = re.compile(r"^## +(\S.*?)\s*$", re.M)


class PromptError(TinyHarnessError):
    code = "prompt.invalid"


class PromptFrontMatter(BaseModel, extra="forbid"):
    """Optional front matter of a prompt file."""

    id: str | None = None
    extends: str | None = None


class PromptSection(BaseModel, frozen=True):
    name: str
    body: str


def split_front_matter(text: str) -> tuple[Mapping[str, object], str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    try:
        loaded: object = yaml.safe_load(match.group(1))
        if loaded is None:
            loaded = {}
    except yaml.YAMLError as exc:
        raise PromptError(f"front matter is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise PromptError("front matter must be a mapping")
    mapping = cast(Mapping[object, object], loaded)
    return {str(k): v for k, v in mapping.items()}, text[match.end() :]


def parse_sections(body: str) -> tuple[PromptSection, ...]:
    """Split a markdown body on ``##`` headings; text before the first heading is ``preamble``."""
    sections: list[PromptSection] = []
    matches = list(_HEADING.finditer(body))
    preamble = body[: matches[0].start()].strip() if matches else body.strip()
    if preamble:
        sections.append(PromptSection(name="preamble", body=preamble))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append(
            PromptSection(name=match.group(1).strip().lower(), body=body[match.end() : end].strip())
        )
    return tuple(sections)


class PromptEntity(Entity):
    """A prompt: its raw text, its sections, and the section it extends, if any."""

    kind = EntityKind.PROMPT

    def __init__(
        self,
        ref: EntityRef,
        text: str,
        *,
        extends: str | None = None,
        sections: tuple[PromptSection, ...] | None = None,
    ) -> None:
        super().__init__(ref)
        self.text = text
        self.extends = extends
        self.sections = sections if sections is not None else parse_sections(text)

    def section(self, name: str) -> str | None:
        for section in self.sections:
            if section.name == name:
                return section.body
        return None

    @classmethod
    def from_file(
        cls, path: Path, *, id: str | None = None, version: str | None = None
    ) -> PromptEntity:
        try:
            raw = path.read_text()
        except OSError as exc:
            raise PromptError(f"cannot read prompt file: {exc}", path=str(path)) from exc
        meta, body = split_front_matter(raw)
        try:
            front = PromptFrontMatter.model_validate(meta)
        except ValidationError as exc:
            raise PromptError(f"invalid prompt front matter: {exc}", path=str(path)) from exc
        prompt_id = id or front.id or path.stem
        ref = EntityRef(kind=EntityKind.PROMPT, id=prompt_id, version=version)
        return cls(ref, body.strip() + "\n", extends=front.extends)


class SystemPrompt:
    """The composed system prompt: the base sections, extended by prompts that ``extends`` them."""

    def __init__(self, base: PromptEntity, extensions: Iterable[PromptEntity] = ()) -> None:
        self._base = base
        self._extensions = tuple(extensions)

    @property
    def base(self) -> PromptEntity:
        return self._base

    def sections(self) -> tuple[PromptSection, ...]:
        extras: dict[str, list[str]] = {}
        for ext in self._extensions:
            if ext.extends is None:
                raise PromptError(
                    "a system-prompt extension must say what it extends", id=ext.ref.id
                )
            extras.setdefault(ext.extends, []).append(ext.text.strip())
        out: list[PromptSection] = []
        seen: set[str] = set()
        for section in self._base.sections:
            seen.add(section.name)
            body = "\n\n".join([section.body, *extras.get(section.name, [])]).strip()
            out.append(PromptSection(name=section.name, body=body))
        for name in extras:
            if name not in seen:
                raise PromptError("extension targets a section the base prompt lacks", section=name)
        return tuple(out)

    def render(self, only: Iterable[str] | None = None) -> str:
        wanted = None if only is None else set(only)
        parts = [
            f"## {s.name}\n\n{s.body}" if s.name != "preamble" else s.body
            for s in self.sections()
            if wanted is None or s.name in wanted
        ]
        return "\n\n".join(parts) + "\n"


__all__ = [
    "SECTION_ORDER",
    "SYSTEM_PROMPT_ID",
    "PromptEntity",
    "PromptError",
    "PromptFrontMatter",
    "PromptSection",
    "SystemPrompt",
    "parse_sections",
    "split_front_matter",
]
