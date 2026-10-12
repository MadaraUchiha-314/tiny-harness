"""The status extension: why a task is ``INPUT_REQUIRED`` (R4.1-R4.4).

A2A's ``TaskStatus`` has no metadata field, so the sub-state lives in two documented
places: ``Task.metadata[STATUS_EXT_KEY]`` (written by ``HarnessTask.with_state``) and the
metadata of the ``TaskStatusUpdateEvent`` that reports the change. The state itself stays
the standard ``TASK_STATE_INPUT_REQUIRED``; the schema leaves ``sub_state`` an open string
so a later value is additive, and a reader treats an unknown one as plain
``INPUT_REQUIRED`` (R4.3).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

STATUS_EXT_URI: Final = "https://madarauchiha-314.github.io/tiny-harness/a2a/ext/status/v1"
STATUS_EXT_KEY: Final = "io.github.madarauchiha-314.tiny-harness/status"


class SubState(StrEnum):
    AWAITING_NEXT_MESSAGE = "awaiting-next-message"
    AWAITING_ANSWER = "awaiting-answer"


class StatusExtensionData(BaseModel, frozen=True):
    """What the status extension carries under ``STATUS_EXT_KEY``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sub_state: SubState


__all__ = ["STATUS_EXT_KEY", "STATUS_EXT_URI", "StatusExtensionData", "SubState"]
