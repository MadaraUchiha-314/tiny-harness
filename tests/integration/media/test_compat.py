"""Feature: 0.8.0 tasks keep working
Requirement: docs/specs/issue-38/requirements.md#R5 (NFR durability, T10)

The media fields are additive with defaults (``MessageItem.media``, ``LLMModelInfo``'s
modalities, ``IntakeOut.media``, ``ToolOut.urls``, ``CompactionSummariseIn``'s media), so a
workflow history recorded by 0.8.0 replays on this code without a nondeterminism error,
and an ``AgentState`` and a ``StateRecord`` stored by 0.8.0 deserialise unchanged.

The fixtures under ``tests/fixtures/compat/0.8.0/`` were recorded by running the 0.8.0
code (commit 849a91b, in a temporary worktree) over the Temporal dev server: alice asks
"where is 48213?", the model calls ``orders.get_order`` and answers, alice says "thanks",
the model says "Bye.", and the task is cancelled. ``task_workflow_history.json`` is that
workflow's history; ``agent_state.json`` is the last ``persist`` activity's state, and
``state_record.json`` the store's last state row.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from temporalio.client import WorkflowHistory

from tiny_harness.harness.core import AgentState
from tiny_harness.harness.models import MessageItem, ToolCallItem, ToolResultItem
from tiny_harness.harness.persistence import StateRecord
from tiny_harness.jsontypes import JsonValue
from tiny_harness.service.durable.worker import build_replayer

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "compat" / "0.8.0"


def without_new_defaults(new: JsonValue, old: JsonValue) -> JsonValue:
    """``new`` less every key ``old`` lacks whose value is an empty default (``None``, an
    empty list): what a field added since 0.8.0 writes for a 0.8.0 value."""
    if isinstance(new, dict) and isinstance(old, dict):
        return {
            k: without_new_defaults(v, old.get(k))
            for k, v in new.items()
            if k in old or v not in (None, [])
        }
    if isinstance(new, list) and isinstance(old, list) and len(new) == len(old):
        return [without_new_defaults(n, o) for n, o in zip(new, old, strict=True)]
    return new


@pytest.mark.asyncio
async def test_a_0_8_0_history_replays_unchanged() -> None:
    """
    Feature: 0.8.0 tasks keep working
    Requirement: docs/specs/issue-38/requirements.md#R5

    Scenario: a 0.8.0 workflow history replays on this code
        Given the history of a 0.8.0 conversation with a tool call, two turns and a cancel
        When it is replayed against this code's TaskWorkflow
        Then the replay finishes without a nondeterminism error
    """
    raw = (FIXTURES / "task_workflow_history.json").read_text()
    history = WorkflowHistory.from_json("t-1", raw)
    result = await build_replayer().replay_workflow(history, raise_on_replay_failure=False)
    assert result.replay_failure is None, result.replay_failure


def test_a_0_8_0_agent_state_deserialises_unchanged() -> None:
    """
    Feature: 0.8.0 tasks keep working
    Requirement: docs/specs/issue-38/requirements.md#R5

    Scenario: a 0.8.0 agent state and state record deserialise
        Given an AgentState and a StateRecord written by 0.8.0
        When this code reads them
        Then every message has no media, and the rest is as written
        And writing the state again gives back the 0.8.0 fields, plus empty defaults only
    """
    raw = cast(JsonValue, json.loads((FIXTURES / "agent_state.json").read_text()))
    state = AgentState.model_validate(raw)
    kinds = [type(e.item) for e in state.history]
    assert kinds == [
        MessageItem,
        ToolCallItem,
        ToolResultItem,
        MessageItem,
        MessageItem,
        MessageItem,
    ]
    messages = [e.item for e in state.history if isinstance(e.item, MessageItem)]
    assert [m.text for m in messages] == [
        "[alice] where is 48213?",
        "Order 48213 shipped.",
        "[alice] thanks",
        "Bye.",
    ]
    assert all(m.media == () for m in messages)
    dumped = cast(JsonValue, state.model_dump(mode="json"))
    assert without_new_defaults(dumped, raw) == raw
    record = StateRecord.model_validate_json((FIXTURES / "state_record.json").read_text())
    assert (record.task_id, record.turn) == ("t-1", 3)
