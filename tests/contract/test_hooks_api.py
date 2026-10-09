"""T3: the hook machinery's public API is pinned."""

import tiny_harness.harness.hooks
from tests.contract._api import assert_snapshot


def test_hooks_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.hooks)
