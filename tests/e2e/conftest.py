"""End-to-end tests need the live environment (T4).

They skip, with the reason, when a required secret is absent; they never pass silently.
"""

import os

import pytest

REQUIRED = ("OPENAI_API_KEY", "TEMPORAL_API_KEY")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"e2e environment absent: {', '.join(missing)} not set")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
