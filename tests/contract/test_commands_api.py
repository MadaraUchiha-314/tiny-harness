"""T3 (issue-25 R6, R6a, R11.3): the command registry, the command.invoked contexts and
the built-in commands are public API."""

import tiny_harness.harness.commands
from tests.contract._api import assert_snapshot


def test_commands_api_snapshot() -> None:
    assert_snapshot(tiny_harness.harness.commands)
