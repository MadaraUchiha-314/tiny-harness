"""Feature: OpenAI-compatible endpoints
Requirement: docs/specs/issue-19/requirements.md#R1

The whole harness — embedded Temporal, worker, A2A server — with the real OpenAI adapter
pointed by ``[openai] base_url`` at a scripted OpenAI-compatible server on loopback, and
no OpenAI key anywhere.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest
from a2a.client import ClientConfig, create_client
from a2a.types import Message, Part, SendMessageRequest, TaskState
from a2a.types import Role as A2ARole

from tests.integration.compat.conftest import (
    CompatServer,
    chat_body,
    compat_settings,
    responses_body,
)
from tiny_harness.service import RunningHarness, running_harness


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("OPENAI_API_KEY", "TEMPORAL_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(variable, raising=False)


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


async def test_harness_completes_a_task_against_a_responses_endpoint(
    tmp_path: Path, compat_server: CompatServer
) -> None:
    """
    Feature: OpenAI-compatible endpoints
    Requirement: docs/specs/issue-19/requirements.md#R3

    Scenario: Harness completes a task against an OpenAI-compatible Responses endpoint
        Given a scripted OpenAI-compatible server on loopback serving the Responses API
        And the harness configured with that base_url, api responses and no OPENAI_API_KEY
        When a message is sent over A2A
        Then the task reaches COMPLETED
        And every model call reached the server's /v1/responses without an Authorization header
    """
    compat_server.answer((200, responses_body("Hello from a compatible server.")))
    settings = compat_settings(tmp_path, base_url=compat_server.url, api="responses")
    async with running_harness(settings) as harness:
        states = await send(harness, "hello")
    assert states[-1] == TaskState.TASK_STATE_COMPLETED
    assert compat_server.seen, "the model was never called"
    for seen in compat_server.seen:
        assert seen.path == "/v1/responses"
        assert "authorization" not in seen.headers
        assert seen.body["model"] == "compat-model"


async def test_harness_completes_a_task_against_a_chat_completions_endpoint(
    tmp_path: Path, compat_server: CompatServer
) -> None:
    """
    Feature: OpenAI-compatible endpoints
    Requirement: docs/specs/issue-19/requirements.md#R3

    Scenario: Harness completes a task against an OpenAI-compatible Chat Completions endpoint
        Given a scripted OpenAI-compatible server on loopback serving Chat Completions only
        And its replies carry no usage
        And the harness configured with that base_url, api chat_completions and no key
        When a message is sent over A2A
        Then the task reaches COMPLETED
        And every model call reached /v1/chat/completions with the system prompt first
    """
    compat_server.answer((200, chat_body("Hello from a chat-only server.")))
    settings = compat_settings(tmp_path, base_url=compat_server.url, api="chat_completions")
    async with running_harness(settings) as harness:
        states = await send(harness, "hello")
    assert states[-1] == TaskState.TASK_STATE_COMPLETED
    assert compat_server.seen, "the model was never called"
    for seen in compat_server.seen:
        assert seen.path == "/v1/chat/completions"
        assert "authorization" not in seen.headers
        messages = seen.body["messages"]
        assert isinstance(messages, list) and messages[0]["role"] == "system"  # type: ignore[index]


async def test_a_retryable_endpoint_failure_is_retried_and_the_task_completes(
    tmp_path: Path, compat_server: CompatServer
) -> None:
    """
    Feature: OpenAI-compatible endpoints
    Requirement: docs/specs/issue-19/requirements.md#R5

    Scenario: A retryable endpoint failure is retried and the task completes
        Given a scripted OpenAI-compatible server that first answers 503
        When a message is sent over A2A
        Then durable execution retries the model call
        And the task reaches COMPLETED
    """
    compat_server.answer(
        (503, {"error": {"message": "loading model"}}),
        (200, chat_body("Ready now.")),
    )
    settings = compat_settings(tmp_path, base_url=compat_server.url, api="chat_completions")
    async with running_harness(settings) as harness:
        states = await send(harness, "hello")
    assert states[-1] == TaskState.TASK_STATE_COMPLETED
    assert len(compat_server.seen) >= 2
