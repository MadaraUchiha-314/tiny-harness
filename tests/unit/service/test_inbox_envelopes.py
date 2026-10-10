"""Feature: Inbox and events
Requirement: docs/specs/issue-3/requirements.md#R15 (R15.1, abuse case 4)

A ``task`` envelope on an existing task changes what its sender is allowed to change.
"""

from __future__ import annotations

import pytest

from tiny_harness.harness.core import Participant, Role, TaskExtensionData
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.inbox import EnvelopeRefused, apply_task_envelope


def ext() -> TaskExtensionData:
    return TaskExtensionData(
        name="Refund",
        goal="Resolve the complaint",
        participants=(
            Participant(id="alice", kind="human", role=Role.REPORTER),
            Participant(id="ops", kind="human", role=Role.ADMIN),
            Participant(id="agent", kind="agent", role=Role.ASSIGNEE),
        ),
    )


def test_any_participant_may_update_the_open_fields() -> None:
    """
    Scenario: any participant may update the open fields
        Given a reporter on the task
        When a task envelope changes the name and the acceptance criteria
        Then the extension carries the change and the participants are untouched
    """
    updated = apply_task_envelope(
        ext(),
        {"name": "Refund #48213", "acceptance_criteria": [{"text": "Refund issued"}]},
        actor="alice",
    )
    assert updated.name == "Refund #48213"
    assert [c.text for c in updated.acceptance_criteria] == ["Refund issued"]
    assert updated.participants == ext().participants


def test_participants_change_needs_an_admin() -> None:
    """
    Scenario: a participants change needs an admin
        Given a reporter and an admin on the task
        When each sends a task envelope that changes the participants
        Then the reporter's is refused with "admin required" and the admin's is applied
    """
    payload: JsonObject = {"participants": [{"id": "alice", "kind": "human", "role": "admin"}]}
    with pytest.raises(EnvelopeRefused, match="admin required"):
        apply_task_envelope(ext(), payload, actor="alice")
    updated = apply_task_envelope(ext(), payload, actor="ops")
    assert [(p.id, p.role) for p in updated.participants] == [("alice", Role.ADMIN)]


def test_unknown_and_invalid_fields_are_refused() -> None:
    """
    Scenario: unknown and invalid fields are refused
        Given a task envelope naming a field the harness owns (the plan) or an invalid value
        When it is applied
        Then it is refused with the reason and nothing changes
    """
    with pytest.raises(EnvelopeRefused, match="cannot change plan"):
        apply_task_envelope(ext(), {"plan": {"steps": []}}, actor="ops")
    with pytest.raises(EnvelopeRefused, match="invalid task extension"):
        apply_task_envelope(ext(), {"acceptance_criteria": "not a list"}, actor="alice")
