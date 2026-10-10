"""T3: the skills loader API is pinned."""

import tiny_harness.harness.skills
from tests.contract._api import assert_snapshot


def test_skills_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.skills)
