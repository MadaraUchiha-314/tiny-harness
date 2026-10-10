"""Shared fixtures for the embedded-mode scenarios: Settings with mode embedded and no
Temporal credentials, and a scripted model in place of OpenAI."""

from __future__ import annotations

import base64
import functools
import os
import socket
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import SecretStr

from tests.integration.durable.conftest import CACHE
from tiny_harness.config import Settings
from tiny_harness.harness.models import FakeLLM, LLMResponse
from tiny_harness.service import process as process_module
from tiny_harness.service.runtime import build_runtime


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def embedded_settings(tmp_path: Path) -> Settings:
    port = free_port()
    return Settings.model_validate(
        {
            "temporal": {
                "mode": "embedded",
                "task_queue": f"embedded-{uuid.uuid4().hex[:8]}",
                "embedded": {"download_dir": str(CACHE)},
            },
            "openai": {"api_key": "sk-unused-the-model-is-scripted"},
            "server": {
                "bind": f"127.0.0.1:{port}",
                "base_url": f"http://127.0.0.1:{port}",
                "bridge_interval": "PT0.05S",
            },
            "store": {"sqlite_path": str(tmp_path / "state" / "tiny-harness.sqlite3")},
            "push_key": SecretStr(base64.b64encode(os.urandom(32)).decode()),
        }
    )


ScriptModel = Callable[..., None]


@pytest.fixture
def script_model(monkeypatch: pytest.MonkeyPatch) -> ScriptModel:
    """Replace the OpenAI model with a script; everything else is the real runtime."""
    monkeypatch.delenv("TEMPORAL_API_KEY", raising=False)

    def use(*responses: LLMResponse) -> None:
        llm = FakeLLM(responses)
        monkeypatch.setattr(
            process_module, "build_runtime", functools.partial(build_runtime, llm=llm)
        )

    use()
    return use


__all__ = ["ScriptModel", "embedded_settings", "free_port", "script_model"]
