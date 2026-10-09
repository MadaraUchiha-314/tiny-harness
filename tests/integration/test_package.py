"""Feature: tiny_harness is installable as a package."""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _uv() -> str:
    uv = shutil.which("uv")
    assert uv is not None, "uv must be on PATH to run the integration tests"
    return uv


def test_built_wheel_installs_and_exposes_the_version(tmp_path: Path) -> None:
    """
    Feature: tiny_harness is installable as a package
    Requirement: docs/specs/issue-2/requirements.md#R2

    Scenario: the built wheel installs and exposes the package version
        Given the wheel built from this checkout with `uv build`
        When it is installed into a fresh virtual environment
        Then `from tiny_harness import __version__` works there
        And the version is the one in pyproject.toml
    """
    uv = _uv()
    dist = tmp_path / "dist"
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist), str(REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    wheels = list(dist.glob("tiny_harness-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, found {wheels}"

    venv = tmp_path / "venv"
    subprocess.run(
        [uv, "venv", "--quiet", "--python", sys.executable, str(venv)], check=True, cwd=tmp_path
    )
    python = venv / "bin" / "python"
    subprocess.run(
        [uv, "pip", "install", "--quiet", "--python", str(python), str(wheels[0])],
        check=True,
        cwd=tmp_path,
    )

    result = subprocess.run(
        [str(python), "-c", "from tiny_harness import __version__; print(__version__)"],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.stdout.strip() == wheels[0].name.split("-")[1]
