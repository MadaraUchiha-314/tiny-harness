"""Agent Skills loader (R5.1, R5.2, R5.4, R5.5): the specification's rules, disclosure levels."""

from pathlib import Path

import pytest

from tiny_harness.errors import SkillError
from tiny_harness.harness.entities import EntityKind
from tiny_harness.harness.skills import SkillLoader, skills_index


def make_skill(root: Path, name: str, front: str, body: str = "# Body\n\nDo the thing.\n") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(f"---\n{front}---\n\n{body}")
    return directory


def test_loads_front_matter_body_and_resources(tmp_path: Path) -> None:
    directory = make_skill(
        tmp_path,
        "summarize",
        "name: summarize\ndescription: Summarise a conversation.\nlicense: Apache-2.0\n"
        "metadata:\n  owner: support\nallowed-tools: Bash(git:*) Read\n",
    )
    (directory / "references").mkdir()
    (directory / "references" / "style.md").write_text("terse")
    (directory / "references" / "deeper").mkdir()
    (directory / "references" / "deeper" / "ignored.md").write_text("x")
    (directory / "scripts").mkdir()
    (directory / "scripts" / "run.sh").write_text("echo")
    skill = SkillLoader().load(directory, version="1.0.0")
    assert skill.ref.kind is EntityKind.SKILL and skill.ref.id == "summarize"
    assert skill.description == "Summarise a conversation."
    assert skill.front_matter.allowed_tools == ("Bash(git:*)", "Read")
    assert skill.front_matter.metadata == {"owner": "support"}
    assert skill.body.startswith("# Body")
    assert [(r.kind, r.name) for r in skill.resources()] == [
        ("scripts", "run.sh"),
        ("references", "style.md"),
    ]
    assert skill.resource("scripts", "run.sh").path.read_text() == "echo"
    with pytest.raises(SkillError):
        skill.resource("references", "deeper/ignored.md")


@pytest.mark.parametrize(
    ("dirname", "front"),
    [
        ("Bad-Name", "name: Bad-Name\ndescription: x\n"),
        ("double--dash", "name: double--dash\ndescription: x\n"),
        ("no-description", "name: no-description\n"),
        ("too-long", "name: too-long\ndescription: " + "x" * 1025 + "\n"),
        ("unknown-field", "name: unknown-field\ndescription: x\nextra: 1\n"),
        ("mismatch", "name: other-name\ndescription: x\n"),
    ],
)
def test_invalid_skills_raise_skill_error(tmp_path: Path, dirname: str, front: str) -> None:
    directory = make_skill(tmp_path, dirname, front)
    with pytest.raises(SkillError):
        SkillLoader().load(directory)


def test_missing_or_empty_front_matter_is_an_error(tmp_path: Path) -> None:
    directory = tmp_path / "plain"
    directory.mkdir()
    (directory / "SKILL.md").write_text("# no front matter\n")
    with pytest.raises(SkillError, match="front matter"):
        SkillLoader().load(directory)
    with pytest.raises(SkillError):
        SkillLoader().load(tmp_path / "absent")


def test_index_is_names_and_descriptions_only(tmp_path: Path) -> None:
    a = SkillLoader().load(make_skill(tmp_path, "alpha", "name: alpha\ndescription: First.\n"))
    b = SkillLoader().load(make_skill(tmp_path, "beta", "name: beta\ndescription: Second.\n"))
    assert skills_index([a, b]) == "- alpha: First.\n- beta: Second."
    assert "Do the thing" not in skills_index([a, b])
