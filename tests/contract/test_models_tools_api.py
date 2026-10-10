"""T3: the model and tool interfaces are pinned."""

import tiny_harness.harness.models
import tiny_harness.harness.tools
from tests.contract._api import assert_snapshot


def test_models_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.models)


def test_tools_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.tools)
