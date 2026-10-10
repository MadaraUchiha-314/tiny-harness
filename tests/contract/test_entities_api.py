"""T3: the entity base API is pinned."""

import tiny_harness.harness.entities
from tests.contract._api import assert_snapshot


def test_entities_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.entities)
