"""Feature: Embedded Temporal mode
Requirement: docs/specs/issue-17/requirements.md#R6

The programmatic entry point runs the whole harness — embedded Temporal, worker, A2A
server — from one ``Settings``, and stops all of it on exit.
"""

from __future__ import annotations

import base64
import functools
import os
import socket
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, SendMessageRequest, TaskState
from a2a.types import Role as A2ARole
from pydantic import SecretStr
from temporalio.client import Client

from tests.integration.durable.conftest import CACHE
from tiny_harness.config import Settings
from tiny_harness.harness.models import FakeLLM, LLMResponse, scripted
from tiny_harness.service import RunningHarness, running_harness
from tiny_harness.service import process as process_module
from tiny_harness.service.durable.worker import SEARCH_ATTRIBUTES
from tiny_harness.service.heartbeat import SCHEDULE_ID
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


async def send(harness: RunningHarness, text: str) -> list[int]:
    """One first message over real HTTP; the states the stream reported."""
    message = Message(
        message_id=uuid.uuid4().hex,
        context_id=f"ctx-{uuid.uuid4().hex[:8]}",
        role=A2ARole.ROLE_USER,
        parts=[Part(text=text)],
    )
    message.metadata.update({"participant_id": "alice"})
    states: list[int] = []
    async with httpx.AsyncClient(timeout=60, headers={"X-Participant-Id": "alice"}) as http:
        client = await create_client(
            harness.base_url,
            client_config=ClientConfig(
                httpx_client=http, streaming=True, supported_protocol_bindings=["JSONRPC"]
            ),
        )
        async for event in client.send_message(SendMessageRequest(message=message)):
            if event.HasField("task"):
                states.append(event.task.status.state)
            elif event.HasField("status_update"):
                states.append(event.status_update.status.state)
        await client.close()
    return states


async def registered_search_attributes(client: Client) -> Sequence[str]:
    from temporalio.api.operatorservice.v1 import ListSearchAttributesRequest

    response = await client.operator_service.list_search_attributes(
        ListSearchAttributesRequest(namespace=client.namespace)
    )
    return list(response.custom_attributes)


async def test_programmatic_harness_runs_a_task_in_embedded_mode(
    tmp_path: Path, script_model: ScriptModel
) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R6

    Scenario: Programmatic harness runs a task in embedded mode
        Given Settings with mode embedded and no Temporal credentials
        When a program enters running_harness(settings)
        Then the A2A server is listening at the configured base URL
        And a message sent over HTTP runs to COMPLETED through the in-process worker
        When the program leaves the context
        Then the A2A server no longer accepts connections
    """
    script_model(scripted("Hello from the embedded harness."))
    settings = embedded_settings(tmp_path)
    async with running_harness(settings, with_worker=False) as harness:  # R5.1: forced on
        assert harness.base_url == str(settings.server.base_url)
        states = await send(harness, "hello")
        assert states[-1] == TaskState.TASK_STATE_COMPLETED
    host, port = process_module.bind_address(settings)
    with socket.socket() as sock:
        assert sock.connect_ex((host, port)) != 0


async def test_embedded_server_registers_search_attributes_and_the_heartbeat_schedule(
    tmp_path: Path, script_model: ScriptModel
) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-17/requirements.md#R2

    Scenario: Embedded server registers search attributes and the heartbeat schedule
        Given Settings with mode embedded
        When running_harness starts
        Then the three keyword search attributes are registered on the embedded server
        And the heartbeat schedule exists on it
    """
    settings = embedded_settings(tmp_path)
    async with running_harness(settings) as harness:
        names = await registered_search_attributes(harness.client)
        assert {key.name for key in SEARCH_ATTRIBUTES} <= set(names)
        description = await harness.client.get_schedule_handle(SCHEDULE_ID).describe()
        assert description.id == SCHEDULE_ID
