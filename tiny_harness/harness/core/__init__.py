"""The core loop and its data: task extension, plan, state, context window, compaction (R8-R10)."""

from tiny_harness.harness.core.proto import PARTICIPANT_KEY, ProtoJson, participant_of, proto_json
from tiny_harness.harness.core.task import (
    TASK_EXT_KEY,
    TASK_EXT_MEDIA_TYPE,
    TASK_EXT_URI,
    TERMINAL_STATES,
    AcceptanceCriterion,
    HarnessTask,
    Participant,
    Plan,
    Role,
    Step,
    StepState,
    TaskExtensionData,
    TaskRef,
    state_name,
)

__all__ = [
    "PARTICIPANT_KEY",
    "TASK_EXT_KEY",
    "TASK_EXT_MEDIA_TYPE",
    "TASK_EXT_URI",
    "TERMINAL_STATES",
    "AcceptanceCriterion",
    "HarnessTask",
    "Participant",
    "Plan",
    "ProtoJson",
    "Role",
    "Step",
    "StepState",
    "TaskExtensionData",
    "TaskRef",
    "participant_of",
    "proto_json",
    "state_name",
]
