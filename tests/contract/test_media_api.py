"""T3: the media package's public API is pinned (issue-38)."""

import tiny_harness.harness.media
from tests.contract._api import assert_snapshot


def test_media_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.media)
