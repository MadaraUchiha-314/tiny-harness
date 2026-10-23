"""End-to-end tests need the live environment (T4).

They skip, with the reason, when a required secret is absent; they never pass silently.
The embedded-mode demo needs only ``OPENAI_API_KEY`` (issue-17), and so does the multi-modal
demo, which runs embedded too (issue-38); the Ollama demo needs no secret and skips when no
local Ollama has the model (issue-19).
"""

import os

import pytest

REQUIRED = ("OPENAI_API_KEY", "TEMPORAL_API_KEY")
REQUIRED_EMBEDDED = ("OPENAI_API_KEY",)  # issue-17: an embedded Temporal needs no account


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "e2e" not in item.keywords:
            continue
        # A live model takes minutes (the local Ollama demo especially); the suite-wide
        # 120 s hang guard (pyproject) is for the offline tests.
        item.add_marker(pytest.mark.timeout(0))
        if "ollama" in item.nodeid:
            continue  # issue-19: no secret at all; the test skips itself when Ollama is absent
        embedded = "embedded" in item.nodeid or "multimodal" in item.nodeid
        required = REQUIRED_EMBEDDED if embedded else REQUIRED
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            reason = f"e2e environment absent: {', '.join(missing)} not set"
            item.add_marker(pytest.mark.skip(reason=reason))
