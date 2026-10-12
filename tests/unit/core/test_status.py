"""The status extension (R4.1, R4.3) and the sub-state on ``with_state`` (R3.3)."""

from __future__ import annotations

import pytest
from a2a.types import TaskState
from google.protobuf import json_format
from pydantic import ValidationError

from tiny_harness.harness.core import (
    STATUS_EXT_KEY,
    STATUS_EXT_URI,
    HarnessTask,
    StatusExtensionData,
    SubState,
    TaskExtensionData,
)


def task() -> HarnessTask:
    return HarnessTask.new("t-1", "ctx-1", TaskExtensionData(name="n", goal="g"))


def test_constants_and_values() -> None:
    assert STATUS_EXT_URI == "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/status/v1"
    assert STATUS_EXT_KEY == "io.github.madarauchiha-314.tiny-harness/status"
    assert {s.value for s in SubState} == {"awaiting-next-message", "awaiting-answer"}
    assert StatusExtensionData(sub_state=SubState.AWAITING_ANSWER).model_dump(mode="json") == {
        "sub_state": "awaiting-answer"
    }
    with pytest.raises(ValidationError):
        StatusExtensionData.model_validate({"sub_state": "awaiting-answer", "extra": 1})


def test_with_state_writes_the_sub_state_into_task_metadata() -> None:
    waiting = task().with_state(
        TaskState.TASK_STATE_INPUT_REQUIRED, sub_state=SubState.AWAITING_NEXT_MESSAGE
    )
    assert waiting.state_name == "INPUT_REQUIRED"
    assert waiting.sub_state is SubState.AWAITING_NEXT_MESSAGE
    raw = json_format.MessageToDict(waiting.proto.metadata.fields[STATUS_EXT_KEY])
    assert raw == {"sub_state": "awaiting-next-message"}


def test_with_state_without_a_sub_state_clears_it() -> None:
    waiting = task().with_state(
        TaskState.TASK_STATE_INPUT_REQUIRED, sub_state=SubState.AWAITING_ANSWER
    )
    resumed = waiting.with_state(TaskState.TASK_STATE_WORKING)
    assert resumed.sub_state is None
    assert STATUS_EXT_KEY not in resumed.proto.metadata.fields
    # the original view is untouched, and the task extension survives both
    assert waiting.sub_state is SubState.AWAITING_ANSWER
    assert resumed.ext.name == "n"


def test_a_task_without_the_key_has_no_sub_state() -> None:
    assert task().sub_state is None


def test_an_unknown_sub_state_reads_as_none() -> None:
    """R4.3: a later sub-state is additive; an older reader treats it as plain INPUT_REQUIRED."""
    waiting = task().with_state(TaskState.TASK_STATE_INPUT_REQUIRED)
    json_format.ParseDict(
        {"sub_state": "awaiting-approval"}, waiting.proto.metadata.fields[STATUS_EXT_KEY]
    )
    assert waiting.sub_state is None
