"""The FastAPI helper (issue-36 R3): ``harness_router`` is the public API of
``tiny_harness.fastapi``."""

import tiny_harness.fastapi
from tests.contract._api import assert_snapshot


def test_fastapi_api_snapshot() -> None:
    assert_snapshot(tiny_harness.fastapi)
