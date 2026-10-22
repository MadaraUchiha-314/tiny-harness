"""Feature: tiny_harness is installable as a package."""

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

import httpx
import pytest

from tiny_harness.harness.media.extension import MEDIA_EXT_URI
from tiny_harness.jsontypes import JsonObject

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


# --- issue-38: the voice and images extras (T12) -------------------------------------------

TUI_PROBE = """
import asyncio, sys
from pathlib import Path

from tiny_harness.harness.media.extension import MediaExtensionParams
from tiny_harness.interaction.tui.app import Entry, HarnessApp
from tiny_harness.interaction.tui.client import ScriptedClient
from tiny_harness.interaction.tui.media import MediaCache, graphics_image_view
from tiny_harness.interaction.tui.voice import INPUT_UNAVAILABLE

MEDIA = MediaExtensionParams(
    input=("image/png", "audio/wav"),
    output=("image/png", "audio/L16;rate=24000;channels=1"),
    speech_to_text=True,
    text_to_speech=True,
    image_generation=True,
)


async def main() -> None:
    assert graphics_image_view() is None, "inline images without the images extra"
    client = ScriptedClient(scripts=[[]], media=MEDIA)
    cache = MediaCache(Path(sys.argv[1]), label="cache")
    app = HarnessApp(client, url="http://127.0.0.1:1", media_cache=cache)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.press("f5")
        await pilot.pause()
        lines = [e.text for e in app.query(Entry)]
        assert f"── {INPUT_UNAVAILABLE}" in lines, lines
        assert app.recording is None
        await pilot.press(*"hello", "enter")
        for _ in range(100):
            if client.sent:
                break
            await pilot.pause(0.05)
        assert client.sent == ["hello"], client.sent
    assert "sounddevice" not in sys.modules and "textual_image" not in sys.modules
    print(INPUT_UNAVAILABLE)


asyncio.run(main())
"""

EXTRAS_PROBE = """
import ctypes.util, importlib, importlib.util

import textual_image.renderable
import textual_image.widget

assert importlib.util.find_spec("sounddevice") is not None
try:
    importlib.import_module("sounddevice")
    print("sounddevice imported")
except OSError as exc:  # the extra is installed, the system library is not
    assert ctypes.util.find_library("portaudio") is None, exc
    assert "PortAudio" in str(exc), exc
    print("sounddevice installed; no PortAudio library on this host")
print("textual_image imported")
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dist = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [_uv(), "build", "--wheel", "--out-dir", str(dist), str(REPO_ROOT)],
        check=True,
        capture_output=True,
    )
    (built,) = dist.glob("tiny_harness-*.whl")
    return built


def _venv(root: Path, requirement: str) -> Path:
    uv = _uv()
    venv = root / "venv"
    subprocess.run(
        [uv, "venv", "--quiet", "--python", sys.executable, str(venv)], check=True, cwd=root
    )
    python = venv / "bin" / "python"
    subprocess.run(
        [uv, "pip", "install", "--quiet", "--python", str(python), requirement],
        check=True,
        cwd=root,
    )
    return venv


def _media_config(root: Path, port: int) -> Path:
    """Embedded Temporal, a loopback model endpoint (no key, never called) and every media
    section on."""
    config = root / "config.toml"
    config.write_text(
        "\n".join(
            [
                "[temporal]",
                'mode = "embedded"',
                f'task_queue = "package-{port}"',
                "[openai]",
                'base_url = "http://127.0.0.1:9/v1"',
                "[media]",
                "[speech_to_text]",
                "[text_to_speech]",
                "[image_generation]",
                "[server]",
                f'bind = "127.0.0.1:{port}"',
                f'base_url = "http://127.0.0.1:{port}"',
                "[store]",
                f'sqlite_path = "{root / "state" / "tiny-harness.sqlite3"}"',
                "",
            ]
        )
    )
    return config


def _card(venv: Path, config: Path, port: int, log: Path) -> JsonObject:
    """Start ``tiny-harness serve`` from the venv, read its agent card, stop it."""
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "TEMPORAL_API_KEY")}
    with log.open("wb") as out:
        server = subprocess.Popen(
            [str(venv / "bin" / "tiny-harness"), "--config", str(config), "serve"],
            cwd=config.parent,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                assert server.poll() is None, log.read_text(errors="replace")[-3000:]
                try:
                    response = httpx.get(
                        f"http://127.0.0.1:{port}/.well-known/agent-card.json", timeout=2
                    )
                    if response.status_code == 200:
                        return cast(JsonObject, response.json())
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            raise AssertionError("the server never answered: " + log.read_text()[-3000:])
        finally:
            server.send_signal(signal.SIGTERM)
            try:
                server.wait(30)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(10)


@pytest.mark.timeout(600)
def test_the_server_and_the_tui_run_without_the_voice_and_images_extras(
    wheel: Path, tmp_path: Path
) -> None:
    """
    Feature: tiny_harness is installable as a package
    Requirement: docs/specs/issue-38/requirements.md#R3.5

    Scenario: a text-only install serves media and opens the TUI without the extras
        Given the wheel built from this checkout, installed without extras
        Then neither sounddevice nor textual_image is installed
        When tiny-harness serve runs with every media section on
        Then its agent card lists image and audio input and the media extension
        When the TUI opens against an agent that accepts audio and F5 is pressed
        Then it says "voice input unavailable: install tiny-harness[voice] (PortAudio)"
        And it shows no inline images and typing a message still sends it
    """
    venv = _venv(tmp_path, str(wheel))
    python = str(venv / "bin" / "python")
    for module in ("sounddevice", "textual_image"):
        probe = subprocess.run(
            [python, "-c", f"import {module}"], capture_output=True, text=True, cwd=tmp_path
        )
        assert probe.returncode != 0, f"{module} is installed without its extra"

    port = _free_port()
    card = _card(venv, _media_config(tmp_path, port), port, tmp_path / "server.log")
    assert "image/png" in cast(list[str], card["defaultInputModes"])
    assert "audio/wav" in cast(list[str], card["defaultInputModes"])
    extensions = cast(list[JsonObject], cast(JsonObject, card["capabilities"])["extensions"])
    assert MEDIA_EXT_URI in [e["uri"] for e in extensions]

    script = tmp_path / "tui_probe.py"
    script.write_text(TUI_PROBE)
    tui = subprocess.run(
        [python, str(script), str(tmp_path / "cache")],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=120,
    )
    assert tui.returncode == 0, tui.stderr[-3000:]
    assert "install tiny-harness[voice]" in tui.stdout


@pytest.mark.timeout(600)
def test_the_voice_and_images_extras_import(wheel: Path, tmp_path: Path) -> None:
    """
    Feature: tiny_harness is installable as a package
    Requirement: docs/specs/issue-38/requirements.md#R8.1

    Scenario: the voice and images extras install what the TUI loads
        Given the wheel built from this checkout, installed as tiny_harness[voice,images]
        Then textual_image imports
        And sounddevice imports, or is installed and names the missing PortAudio library
    """
    venv = _venv(tmp_path, f"{wheel}[voice,images]")
    probe = subprocess.run(
        [str(venv / "bin" / "python"), "-c", EXTRAS_PROBE],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert probe.returncode == 0, probe.stderr[-3000:]
    assert "textual_image imported" in probe.stdout
