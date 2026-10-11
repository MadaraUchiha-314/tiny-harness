"""The Ollama e2e's skip guard (issue-19 T4): it never passes silently without Ollama."""

from __future__ import annotations

from tests.e2e.demo import ollama_unavailable


def test_no_ollama_is_a_skip_reason() -> None:
    reason = ollama_unavailable("qwen3:8b", None)
    assert reason is not None and "no Ollama answering" in reason


def test_a_missing_model_is_a_skip_reason() -> None:
    reason = ollama_unavailable("qwen3:8b", {"models": [{"name": "llama3.2:latest"}]})
    assert reason is not None and "qwen3:8b is not pulled" in reason


def test_a_pulled_model_runs() -> None:
    assert ollama_unavailable("qwen3:8b", {"models": [{"name": "qwen3:8b"}]}) is None
    assert ollama_unavailable("llama3.2", {"models": [{"name": "llama3.2:latest"}]}) is None
