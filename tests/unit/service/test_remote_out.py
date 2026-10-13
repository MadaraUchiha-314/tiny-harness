"""``remote_out`` (issue-27 R2.5): the one mapping a turn, a ``GetTask`` and a follow
share, so every path records a remote task's state the same way."""

from __future__ import annotations

import pytest
from a2a.types import TaskState

from tiny_harness.harness.core import SubState
from tiny_harness.service.durable.activities import remote_out


def test_a_peer_parked_after_its_reply_is_recorded_completed() -> None:
    out = remote_out(
        "r-1", TaskState.TASK_STATE_INPUT_REQUIRED, SubState.AWAITING_NEXT_MESSAGE, "done"
    )
    assert (out.state_name, out.final, out.text) == ("COMPLETED", True, "done")


def test_a_question_stays_input_required() -> None:
    out = remote_out("r-1", TaskState.TASK_STATE_INPUT_REQUIRED, SubState.AWAITING_ANSWER, "?")
    assert (out.state_name, out.final) == ("INPUT_REQUIRED", False)


@pytest.mark.parametrize(
    ("state", "final"),
    [
        (TaskState.TASK_STATE_WORKING, False),
        (TaskState.TASK_STATE_AUTH_REQUIRED, False),
        (TaskState.TASK_STATE_COMPLETED, True),
        (TaskState.TASK_STATE_CANCELED, True),
        (TaskState.TASK_STATE_FAILED, True),
        (TaskState.TASK_STATE_REJECTED, True),
    ],
)
def test_terminal_states_are_final(state: TaskState.ValueType, final: bool) -> None:
    out = remote_out("r-1", state, None, None)
    assert out.final is final
    assert out.text == ""
