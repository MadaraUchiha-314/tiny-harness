"""The programmatic entry points (issue-17 R6): ``running_harness``, ``serve``,
``temporal_client`` and ``RunningHarness`` are the public API of ``tiny_harness.service``."""

import tiny_harness.service
from tests.contract._api import assert_snapshot


def test_service_api_snapshot() -> None:
    assert_snapshot(tiny_harness.service)
