"""End-to-end tests need the live environment (T4).

They skip, with the reason, when a required secret is absent; they never pass silently.
The embedded-mode demo needs only ``OPENAI_API_KEY`` (issue-17).
"""

import os

import pytest

REQUIRED = ("OPENAI_API_KEY", "TEMPORAL_API_KEY")
REQUIRED_EMBEDDED = ("OPENAI_API_KEY",)  # issue-17: an embedded Temporal needs no account


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "e2e" not in item.keywords:
            continue
        required = REQUIRED_EMBEDDED if "embedded" in item.nodeid else REQUIRED
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            reason = f"e2e environment absent: {', '.join(missing)} not set"
            item.add_marker(pytest.mark.skip(reason=reason))
