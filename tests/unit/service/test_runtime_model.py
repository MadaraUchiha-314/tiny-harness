"""What the runtime says about its model (issue-19 NFR observability, abuse case 5): the
endpoint's origin and wire API, never its path, query or the key."""

from __future__ import annotations

from datetime import timedelta

import httpx2
import pytest
from pydantic import SecretStr

from tiny_harness.errors import ProviderError
from tiny_harness.harness.models import LLMRequest, MessageItem, OpenAILLM, Role, scripted
from tiny_harness.harness.models.llm import FakeLLM
from tiny_harness.harness.models.openai_adapter import endpoint_origin, openai_client
from tiny_harness.service.runtime import model_endpoint_line

KEY = "sk-very-secret-key"


def test_the_line_names_origin_api_and_model() -> None:
    llm = OpenAILLM(
        SecretStr(KEY),
        model="qwen3:8b",
        base_url="http://127.0.0.1:11434/v1",
        api="chat_completions",
    )
    line = model_endpoint_line(llm)
    assert line == "model endpoint http://127.0.0.1:11434 api=chat_completions model=qwen3:8b"
    assert KEY not in line


def test_the_default_endpoint_is_named_too() -> None:
    line = model_endpoint_line(OpenAILLM(SecretStr(KEY)))
    assert line == "model endpoint https://api.openai.com api=responses model=gpt-6.1-sol"


def test_a_model_without_an_endpoint_has_no_line() -> None:
    assert model_endpoint_line(FakeLLM([scripted("hi")])) is None


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://h.example:8443/v1?api-key=leak#frag", "https://h.example:8443"),
        ("http://[::1]:11434/v1", "http://[::1]:11434"),
        (None, "https://api.openai.com"),
    ],
)
def test_abuse_the_origin_drops_path_and_query(url: str | None, origin: str) -> None:
    assert endpoint_origin(url) == origin


async def test_abuse_a_translated_error_does_not_carry_the_key() -> None:
    def unauthorized(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "invalid api key"}})

    key = SecretStr(KEY)
    llm = OpenAILLM(
        key,
        base_url="https://openrouter.ai/api/v1",
        client=openai_client(
            key,
            base_url="https://openrouter.ai/api/v1",
            timeout=timedelta(seconds=5),
            transport=httpx2.MockTransport(unauthorized),
        ),
    )
    with pytest.raises(ProviderError) as caught:
        await llm.invoke(
            LLMRequest(instructions="", input=(MessageItem(role=Role.USER, text="hi"),))
        )
    assert KEY not in str(caught.value) and KEY not in repr(caught.value.__dict__)


# R1.3: OPENAI_BASE_URL is ignored, but never silently (self-review round 1, finding 2).


def test_an_exported_openai_base_url_is_warned_about_without_its_value() -> None:
    from tiny_harness.service.runtime import ignored_environment_warning

    line = ignored_environment_warning({"OPENAI_BASE_URL": "http://proxy.internal/v1"})
    assert line is not None
    assert "OPENAI_BASE_URL" in line and "[openai] base_url" in line
    assert "proxy.internal" not in line


@pytest.mark.parametrize("env", [{}, {"OPENAI_BASE_URL": ""}])
def test_no_warning_without_the_variable(env: dict[str, str]) -> None:
    from tiny_harness.service.runtime import ignored_environment_warning

    assert ignored_environment_warning(env) is None
