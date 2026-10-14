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


def test_the_fastapi_helper_needs_its_extra(tmp_path: Path) -> None:
    """
    Feature: tiny_harness is installable as a package
    Requirement: docs/specs/issue-36/requirements.md#R3

    Scenario: the FastAPI helper needs its extra
        Given the wheel built from this checkout, installed without extras
        When tiny_harness.fastapi is imported
        Then the import fails naming the tiny_harness[fastapi] extra
        And with the extra installed the same import succeeds
    """
    uv = _uv()
    dist = tmp_path / "dist"
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist), str(REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    (wheel,) = dist.glob("tiny_harness-*.whl")
    venv = tmp_path / "venv"
    subprocess.run(
        [uv, "venv", "--quiet", "--python", sys.executable, str(venv)], check=True, cwd=tmp_path
    )
    python = venv / "bin" / "python"
    install = [uv, "pip", "install", "--quiet", "--python", str(python)]
    subprocess.run([*install, str(wheel)], check=True, cwd=tmp_path)
    probe = [str(python), "-c", "import tiny_harness.fastapi"]
    bare = subprocess.run(probe, capture_output=True, text=True, cwd=tmp_path)
    assert bare.returncode != 0
    assert "tiny_harness[fastapi]" in bare.stderr
    subprocess.run([*install, f"{wheel}[fastapi]"], check=True, cwd=tmp_path)
    subprocess.run(probe, check=True, cwd=tmp_path)
