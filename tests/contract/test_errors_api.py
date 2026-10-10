"""T3: the error hierarchy's public API is pinned."""

import tiny_harness.errors
from tests.contract._api import assert_snapshot


def test_errors_api_snapshot() -> None:
    assert_snapshot(tiny_harness.errors)
