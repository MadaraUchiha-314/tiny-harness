"""The package mirrors the architecture diagram (design.md § Layers and modules)."""

import importlib
from pathlib import Path

import pytest

import tiny_harness

PACKAGE_ROOT = Path(tiny_harness.__file__).resolve().parent

# One module per diagram box, grouped by column (design.md, R22.1).
MODULES = [
    "tiny_harness.config",
    "tiny_harness.errors",
    "tiny_harness.builtin",
    "tiny_harness.interaction",
    "tiny_harness.interaction.surface",
    "tiny_harness.interaction.renderer",
    "tiny_harness.interaction.a2ui",
    "tiny_harness.interaction.tui",
    "tiny_harness.service",
    "tiny_harness.service.a2a",
    "tiny_harness.service.inbox",
    "tiny_harness.service.heartbeat",
    "tiny_harness.service.channels",
    "tiny_harness.service.o11y",
    "tiny_harness.service.durable",
    "tiny_harness.harness",
    "tiny_harness.harness.entities",
    "tiny_harness.harness.hooks",
    "tiny_harness.harness.plugins",
    "tiny_harness.harness.prompts",
    "tiny_harness.harness.skills",
    "tiny_harness.harness.tools",
    "tiny_harness.harness.models",
    "tiny_harness.harness.core",
    "tiny_harness.harness.persistence",
    "tiny_harness.harness.channels",
    "tiny_harness.harness.agents",
    "tiny_harness.harness.security",
]


@pytest.mark.parametrize("name", MODULES)
def test_modules_mirror_diagram(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__doc__, f"{name} has no docstring"


def test_package_has_no_example_function() -> None:
    assert not hasattr(tiny_harness, "hello_world")
    assert not (PACKAGE_ROOT / "hello.py").exists()


def test_package_exposes_a_version() -> None:
    assert isinstance(tiny_harness.__version__, str) and tiny_harness.__version__
