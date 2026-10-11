"""The OpenAI adapter against any endpoint (issue-19 R1, R2, R4; abuse case 1): the URL a
request reaches, the headers it carries, redirects refused, and the model info."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from tiny_harness.errors import ProviderError
from tiny_harness.harness.models import LLMRequest, MessageItem, OpenAILLM, Role
from tiny_harness.harness.models.openai_adapter import DEFAULT_BASE_URL, openai_client

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openai"
LOCAL = "http://127.0.0.1:11434/v1"
Handler = Callable[[httpx2.Request], httpx2.Response]


class Recorder:
    """A transport that answers every request with a recorded Responses body."""

    def __init__(self, respond: Handler | None = None) -> None:
        self.requests: list[httpx2.Request] = []
        self._respond = respond

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self._respond is not None:
            return self._respond(request)
        return httpx2.Response(200, json=json.loads((FIXTURES / "response_text.json").read_text()))

    @property
    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self)


def adapter(
    recorder: Recorder,
    *,
    api_key: str | None = "sk-test",
    base_url: str | None = LOCAL,
    model: str = "gpt-6.1-sol",
    context_window_tokens: int | None = None,
) -> OpenAILLM:
    key = SecretStr(api_key) if api_key is not None else None
    client = openai_client(
        key, base_url=base_url, timeout=timedelta(seconds=5), transport=recorder.transport
    )
    return OpenAILLM(
        key,
        model=model,
        base_url=base_url,
        context_window_tokens=context_window_tokens,
        client=client,
    )


def request() -> LLMRequest:
    return LLMRequest(instructions="be brief", input=(MessageItem(role=Role.USER, text="hi"),))


# R1.1, R1.2 — where a request goes.


async def test_a_base_url_receives_the_request() -> None:
    recorder = Recorder()
    await adapter(recorder).invoke(request())
    assert str(recorder.requests[0].url) == f"{LOCAL}/responses"


async def test_without_a_base_url_the_request_goes_to_openai() -> None:
    recorder = Recorder()
    await adapter(recorder, base_url=None).invoke(request())
    assert str(recorder.requests[0].url) == f"{DEFAULT_BASE_URL}/responses"


@pytest.mark.parametrize("base_url", [LOCAL, None])
async def test_abuse_openai_base_url_in_the_environment_is_ignored(
    monkeypatch: pytest.MonkeyPatch, base_url: str | None
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://evil.invalid/v1")
    recorder = Recorder()
    await adapter(recorder, base_url=base_url).invoke(request())
    assert recorder.requests[0].url.host != "evil.invalid"


# R1.5 — the model name is the server's business.


@pytest.mark.parametrize("model", ["qwen3:8b", "openai/gpt-oss-120b"])
async def test_the_model_name_is_sent_verbatim(model: str) -> None:
    recorder = Recorder()
    await adapter(recorder, model=model).invoke(request())
    assert json.loads(recorder.requests[0].content)["model"] == model


# R2.2, R2.3 — the key.


async def test_a_keyless_endpoint_gets_no_authorization_header() -> None:
    recorder = Recorder()
    await adapter(recorder, api_key=None).invoke(request())
    assert "authorization" not in recorder.requests[0].headers


async def test_a_keyless_stream_gets_no_authorization_header() -> None:
    sse = (FIXTURES / "stream.sse").read_bytes()
    recorder = Recorder(
        lambda _: httpx2.Response(200, content=sse, headers={"content-type": "text/event-stream"})
    )
    async for _ in adapter(recorder, api_key=None).stream(request()):
        pass
    assert "authorization" not in recorder.requests[0].headers


async def test_a_key_is_sent_as_the_bearer_token() -> None:
    recorder = Recorder()
    await adapter(recorder).invoke(request())
    assert recorder.requests[0].headers["authorization"] == "Bearer sk-test"


def test_a_keyless_adapter_needs_a_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        OpenAILLM(None)


# Design § client: the organization and project never reach a third-party endpoint.


async def test_organization_and_project_are_not_sent_to_a_custom_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_ORG_ID", "org-private")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "proj-private")
    recorder = Recorder()
    await adapter(recorder).invoke(request())
    headers = recorder.requests[0].headers
    assert "openai-organization" not in headers
    assert "openai-project" not in headers


async def test_organization_is_still_sent_to_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_ORG_ID", "org-private")
    recorder = Recorder()
    await adapter(recorder, base_url=None).invoke(request())
    assert recorder.requests[0].headers["openai-organization"] == "org-private"


# R1.1 — a redirect never takes the request to another host.


async def test_abuse_a_redirect_from_a_custom_endpoint_is_refused() -> None:
    def respond(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "elsewhere.invalid":
            return httpx2.Response(200, json={})
        return httpx2.Response(307, headers={"location": "http://elsewhere.invalid/v1/responses"})

    recorder = Recorder(respond)
    with pytest.raises(ProviderError) as caught:
        await adapter(recorder).invoke(request())
    assert caught.value.status == 307
    assert [r.url.host for r in recorder.requests] == ["127.0.0.1"]


# R4.1, R4.2 and the observability fields of the model info.


def test_context_window_tokens_overrides_the_table() -> None:
    info = adapter(Recorder(), model="qwen3:8b", context_window_tokens=16384).info
    assert info.context_window_tokens == 16384


@pytest.mark.parametrize(("model", "window"), [("gpt-6-luna", 400_000), ("qwen3:8b", 400_000)])
def test_without_an_override_the_table_and_default_stand(model: str, window: int) -> None:
    assert adapter(Recorder(), model=model).info.context_window_tokens == window


def test_model_info_names_the_endpoint_and_the_api() -> None:
    info = adapter(Recorder()).info
    assert info.endpoint == "http://127.0.0.1:11434"
    assert info.api == "responses"
    default = adapter(Recorder(), base_url=None).info
    assert default.endpoint == "https://api.openai.com"
