"""Feature: Embedded Temporal mode
Requirement: docs/specs/issue-17/requirements.md#R6

The programmatic entry point runs the whole harness — embedded Temporal, worker, A2A
server — from one ``Settings``, and stops all of it on exit.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, SendMessageRequest, TaskState
from a2a.types import Role as A2ARole
from temporalio.client import Client

from tests.integration.embedded.conftest import ScriptModel, embedded_settings
from tiny_harness.harness.commands import (
    COMMANDS_EXT_URI,
    CommandInvokedIn,
    CommandResult,
    CommandSpec,
)
from tiny_harness.harness.models import scripted
from tiny_harness.service import RunningHarness, running_harness
from tiny_harness.service import process as process_module
from tiny_harness.service.durable.worker import SEARCH_ATTRIBUTES
from tiny_harness.service.heartbeat import SCHEDULE_ID


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


async def replies(harness: RunningHarness, text: str) -> list[str]:
    """One first message over real HTTP; the text of each status message the stream
    carried."""
    message = Message(
        message_id=uuid.uuid4().hex,
        context_id=f"ctx-{uuid.uuid4().hex[:8]}",
        role=A2ARole.ROLE_USER,
        parts=[Part(text=text)],
    )
    message.metadata.update({"participant_id": "alice"})
    texts: list[str] = []
    async with httpx.AsyncClient(timeout=60, headers={"X-Participant-Id": "alice"}) as http:
        client = await create_client(
            harness.base_url,
            client_config=ClientConfig(
                httpx_client=http, streaming=True, supported_protocol_bindings=["JSONRPC"]
            ),
        )
        async for event in client.send_message(SendMessageRequest(message=message)):
            if event.HasField("status_update") and event.status_update.status.message.parts:
                texts.append(event.status_update.status.message.parts[0].text)
            elif event.HasField("task") and event.task.status.message.parts:
                texts.append(event.task.status.message.parts[0].text)
        await client.close()
    return texts


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
        And a message sent over HTTP reaches INPUT_REQUIRED through the in-process worker
        When the program leaves the context
        Then the A2A server no longer accepts connections
    """
    script_model(scripted("Hello from the embedded harness."))
    settings = embedded_settings(tmp_path)
    async with running_harness(settings, with_worker=False) as harness:  # R5.1: forced on
        assert harness.base_url == str(settings.server.base_url)
        states = await send(harness, "hello")
        assert states[-1] == TaskState.TASK_STATE_INPUT_REQUIRED  # issue-25 R3.1
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


async def test_an_sdk_harness_serves_its_own_commands_and_never_touches_home(
    tmp_path: Path, script_model: ScriptModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Feature: Embedded Temporal mode
    Requirement: docs/specs/issue-25/requirements.md#R11

    Scenario: An SDK harness serves its own commands and never touches the home directory
        Given an empty HOME
        And a program that registers "/echo" from code and builds without the built-ins
        When it enters running_harness(settings, commands=..., builtin_commands=False)
        Then the served agent card's commands extension lists only "/echo"
        And "/echo hi" sent over HTTP replies "hi" without a model call
        And nothing was created under HOME
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    script_model()  # no model response is scripted: a model call would fail the turn
    spec = CommandSpec(name="echo", description="Echo", argument_hint="<text>")

    def echo(ctx: CommandInvokedIn) -> CommandResult:
        return CommandResult(reply=ctx.arguments)

    settings = embedded_settings(tmp_path)
    async with running_harness(
        settings, commands=[(spec, echo)], builtin_commands=False
    ) as harness:
        async with httpx.AsyncClient(timeout=30) as http:
            card = (
                await http.get(f"{harness.base_url.rstrip('/')}/.well-known/agent-card.json")
            ).json()
        extensions = {e["uri"]: e for e in card["capabilities"]["extensions"]}
        assert extensions[COMMANDS_EXT_URI]["params"] == {
            "commands": [{"name": "echo", "description": "Echo", "argument_hint": "<text>"}]
        }
        texts = await replies(harness, "/echo hi")
    assert texts[-1] == "hi"
    assert list(home.iterdir()) == []
