"""T3: the plugin loader's public API is pinned."""

import tiny_harness.harness.plugins
from tests.contract._api import assert_snapshot


def test_plugins_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.plugins)
