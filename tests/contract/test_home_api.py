"""T3 (issue-25 R11.1): the configuration-path functions the CLI uses are public API."""

import tiny_harness.home
from tests.contract._api import assert_snapshot


def test_home_api_snapshot() -> None:
    assert_snapshot(tiny_harness.home)
