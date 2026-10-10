"""Feature: Inbox and events
Requirement: docs/specs/issue-3/requirements.md#R15

A task envelope on an existing task reaches the workflow through intake (R15.1).
"""

from __future__ import annotations

import uuid

import pytest
from a2a.types import Message, Part, TaskState
from a2a.types import Role as A2ARole
from google.protobuf import struct_pb2
from temporalio.testing import WorkflowEnvironment

from tests.integration.durable.conftest import Harness, send, start, task
from tiny_harness.harness.core import HarnessTask, Participant, Role, TaskExtensionData
from tiny_harness.harness.models import scripted
from tiny_harness.jsontypes import JsonObject
from tiny_harness.service.a2a.card import EVENT_MEDIA_TYPE

pytestmark = pytest.mark.asyncio(loop_scope="module")


def envelope_message(
    payload: JsonObject, *, participant: str, task_id: str, message_id: str
) -> Message:
    value = struct_pb2.Value()
    value.struct_value.update({"kind": "task", "payload": payload})
    msg = Message(
        message_id=message_id,
        context_id="ctx-1",
        task_id=task_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(text="please update the task"), Part(data=value, media_type=EVENT_MEDIA_TYPE)],
    )
    msg.metadata.update({"participant_id": participant})
    return msg


def task_with_admin(task_id: str) -> HarnessTask:
    base = task(task_id)
    return base.with_ext(
        base.ext.model_copy(
            update={
                "participants": (
                    *base.ext.participants,
                    Participant(id="ops", kind="human", role=Role.ADMIN),
                )
            }
        )
    )


async def test_a_task_envelope_updates_an_existing_task_within_its_senders_rights(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Inbox and events
    Requirement: docs/specs/issue-3/requirements.md#R15

    Scenario: a task envelope updates an existing task within its sender's rights
        Given a task with a reporter and an admin
        When the reporter sends a task envelope with new acceptance criteria
        And the reporter sends one that changes the participants
        And the admin sends the same participants change
        Then the criteria change, the reporter's participants change is refused
        And the admin's is applied, all visible on the final task
    """
    tq = f"tq-{uuid.uuid4().hex[:8]}"
    task_id = f"t-{uuid.uuid4().hex[:8]}"
    h = await Harness([scripted("Noted."), scripted("Noted."), scripted("Done.")]).bind()
    t = task_with_admin(task_id)
    async with h.worker(env.client, tq):
        handle = await send(
            env.client,
            tq,
            start(t),
            envelope_message(
                {"acceptance_criteria": [{"text": "Refund issued"}]},
                participant="alice",
                task_id=task_id,
                message_id="m1",
            ),
        )
        await send(
            env.client,
            tq,
            start(t),
            envelope_message(
                {"participants": [{"id": "alice", "kind": "human", "role": "admin"}]},
                participant="alice",
                task_id=task_id,
                message_id="m2",
            ),
        )
        await send(
            env.client,
            tq,
            start(t),
            envelope_message(
                {
                    "participants": [
                        {"id": "alice", "kind": "human", "role": "reporter"},
                        {"id": "ops", "kind": "human", "role": "admin"},
                        {"id": "agent", "kind": "agent", "role": "assignee"},
                        {"id": "bob", "kind": "human", "role": "watcher"},
                    ]
                },
                participant="ops",
                task_id=task_id,
                message_id="m3",
            ),
        )
        result = await handle.result()
    assert result.status.state == TaskState.TASK_STATE_COMPLETED
    ext = HarnessTask(result).ext
    assert [c.text for c in ext.acceptance_criteria] == ["Refund issued"]
    assert [p.id for p in ext.participants] == ["alice", "ops", "agent", "bob"]
    assert isinstance(ext, TaskExtensionData)
