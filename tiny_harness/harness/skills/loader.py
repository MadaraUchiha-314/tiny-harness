"""Agent Skills loader (R5.1, R5.2, R5.4, R5.5).

A skill is a directory named after its ``name`` field holding ``SKILL.md`` (YAML front
matter plus a markdown body) and optional ``scripts/``, ``references/`` and ``assets/``
directories, one level deep. The loader is the harness's own: the specification's
reference implementation is demo-grade and untyped. Validation follows the
specification's rules (name pattern and length, description length, compatibility
length, ``allowed-tools`` space separated); an invalid skill is a ``SkillError`` the
caller records and skips, never a crash.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from tiny_harness.errors import SkillError
from tiny_harness.harness.entities import Entity, EntityKind, EntityRef
from tiny_harness.harness.prompts import split_front_matter

RESOURCE_DIRS: tuple[str, ...] = ("scripts", "references", "assets")
SkillName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)]


class SkillFrontMatter(BaseModel):
    """The front matter of ``SKILL.md`` as the specification defines it."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: SkillName
    description: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    license: str | None = None
    compatibility: Annotated[str, StringConstraints(max_length=500)] | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    allowed_tools: tuple[str, ...] = Field(default=(), alias="allowed-tools")

    @field_validator("allowed_tools", mode="before")
    @classmethod
    def _split_allowed_tools(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(value.split())
        return value


class SkillResource(BaseModel, frozen=True):
    """One file under ``scripts/``, ``references/`` or ``assets/``."""

    kind: Literal["scripts", "references", "assets"]
    name: str
    path: Path


class Skill(Entity):
    """A loaded skill: front matter (level 1), body (level 2) and resources (level 3)."""

    kind = EntityKind.SKILL

    def __init__(
        self, ref: EntityRef, front_matter: SkillFrontMatter, body: str, root: Path
    ) -> None:
        super().__init__(ref)
        self.front_matter = front_matter
        self.body = body
        self.root = root

    @property
    def name(self) -> str:
        return self.front_matter.name

    @property
    def description(self) -> str:
        return self.front_matter.description

    def resources(self) -> Sequence[SkillResource]:
        """Files one level deep under the three resource directories, sorted."""
        found: list[SkillResource] = []
        for kind in RESOURCE_DIRS:
            directory = self.root / kind
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if path.is_file() and path.resolve().is_relative_to(self.root.resolve()):
                    found.append(SkillResource(kind=kind, name=path.name, path=path))  # type: ignore[arg-type]
        return found

    def resource(self, kind: str, name: str) -> SkillResource:
        for res in self.resources():
            if res.kind == kind and res.name == name:
                return res
        raise SkillError("no such skill resource", skill=self.name, kind=kind, name=name)


class SkillLoader:
    """Loads one skill directory into a ``Skill`` or raises ``SkillError`` (R5.4)."""

    def load(self, directory: Path, *, version: str | None = None) -> Skill:
        skill_md = directory / "SKILL.md"
        try:
            raw = skill_md.read_text()
        except OSError as exc:
            raise SkillError(f"cannot read SKILL.md: {exc}", path=str(skill_md)) from exc
        try:
            meta, body = split_front_matter(raw)
        except Exception as exc:  # the prompt splitter raises its own typed error
            raise SkillError(f"invalid front matter: {exc}", path=str(skill_md)) from exc
        if not meta:
            raise SkillError("SKILL.md has no front matter", path=str(skill_md))
        try:
            front = SkillFrontMatter.model_validate(meta)
        except ValidationError as exc:
            raise SkillError(
                f"front matter fails the Agent Skills rules: {exc}", path=str(skill_md)
            ) from exc
        if directory.name != front.name:
            raise SkillError(
                "skill directory must be named after the skill",
                directory=directory.name,
                name=front.name,
            )
        ref = EntityRef(kind=EntityKind.SKILL, id=front.name, version=version)
        return Skill(ref, front, body.strip() + "\n", directory.resolve())


def skills_index(skills: Sequence[Skill]) -> str:
    """Level-1 disclosure: names and descriptions only (R5.3)."""
    return "\n".join(f"- {s.name}: {s.description}" for s in skills)


__all__ = [
    "RESOURCE_DIRS",
    "Skill",
    "SkillFrontMatter",
    "SkillLoader",
    "SkillResource",
    "skills_index",
]
