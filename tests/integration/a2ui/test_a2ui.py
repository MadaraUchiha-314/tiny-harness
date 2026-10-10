"""Feature: A2UI
Requirement: docs/specs/issue-3/requirements.md#R20

The harness emits A2UI 0.9.1 messages as application/a2ui+json parts and accepts actions
only for surfaces and components it created.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from a2a.types import Artifact, Message, Part, SendMessageRequest, TaskState
from a2a.types import Role as A2ARole
from google.protobuf import json_format, struct_pb2
from temporalio.testing import WorkflowEnvironment

from tests.integration.a2a.conftest import env, make_server
from tests.integration.a2a.test_server import user_message
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import Filter, InboxAuditRecord
from tiny_harness.harness.tools import ToolCall
from tiny_harness.interaction.a2ui import A2UI_MEDIA_TYPE, A2UI_VERSION, BASIC_CATALOG_ID, Action

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]

EMIT = ToolCall(
    call_id="c1",
    name="emit_ui",
    arguments={
        "messages": [
            {
                "version": A2UI_VERSION,
                "createSurface": {"surfaceId": "resolution", "catalogId": BASIC_CATALOG_ID},
            },
            {
                "version": A2UI_VERSION,
                "updateComponents": {
                    "surfaceId": "resolution",
                    "components": [
                        {"id": "root", "component": "Column", "children": ["q", "pick", "ok"]},
                        {"id": "q", "component": "Text", "text": "Proposed resolution"},
                        {
                            "id": "pick",
                            "component": "ChoicePicker",
                            "label": "Resolution",
                            "options": [
                                {"label": "Ship replacement now", "value": "replace"},
                                {"label": "Refund after photo", "value": "refund"},
                            ],
                            "value": {"path": "/choice"},
                        },
                        {
                            "id": "ok",
                            "component": "Button",
                            "child": "ok-label",
                            "action": {
                                "event": {
                                    "name": "confirm",
                                    "context": {"choice": {"path": "/choice"}},
                                }
                            },
                        },
                        {"id": "ok-label", "component": "Text", "text": "Confirm"},
                    ],
                },
            },
        ]
    },
)
ASK = ToolCall(
    call_id="c2",
    name="ask_participant",
    arguments={"participant_id": "alice", "question": "Confirm the resolution on the card"},
)


def action_message(
    action: Action, *, task_id: str, context_id: str, participant: str = "alice"
) -> Message:
    value = struct_pb2.Value()
    value.struct_value.update(action.payload())
    msg = Message(
        message_id=uuid.uuid4().hex,
        task_id=task_id,
        context_id=context_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(data=value, media_type=A2UI_MEDIA_TYPE)],
    )
    msg.metadata.update({"participant_id": participant})
    return msg


async def test_emit_ui_streams_a2ui_parts_and_an_action_from_the_renderer_reaches_the_task(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: A2UI
    Requirement: docs/specs/issue-3/requirements.md#R20

    Scenario: emit_ui streams A2UI parts and an action from the renderer reaches the task
        Given the LLM emits a surface with a choice picker and a confirm button, then asks alice
        When the client streams the task
        Then it receives one artifact update whose parts are application/a2ui+json
        When a forged action names a component the task did not create
        Then it is refused at intake and the task still waits
        When the genuine confirm action arrives as an A2UI part
        Then the task resumes with the action in context and completes
    """
    suffix = uuid.uuid4().hex[:8]
    context_id = f"ctx-{suffix}"
    server = await make_server(
        env,
        [
            scripted("", tool_calls=[EMIT]),
            scripted("", tool_calls=[ASK]),
            scripted("Replacement shipped."),
        ],
        task_queue=f"tq-{suffix}",
    )
    async with server:
        task_id = ""
        artifacts: list[Artifact] = []
        async for event in server.a2a().send_message(
            SendMessageRequest(message=user_message("refund 48213", context_id=context_id))
        ):
            if event.HasField("task"):
                task_id = event.task.id
            if event.HasField("artifact_update"):
                artifacts.append(event.artifact_update.artifact)
        assert task_id
        assert len(artifacts) == 1, "one artifact update carries the A2UI messages"
        assert artifacts[0].name == "a2ui"
        parts = artifacts[0].parts
        assert [p.media_type for p in parts] == [A2UI_MEDIA_TYPE, A2UI_MEDIA_TYPE]
        payloads = [json_format.MessageToDict(p.data) for p in parts]
        assert "createSurface" in payloads[0] and "updateComponents" in payloads[1]
        forged = Action(
            name="confirm", surfaceId="resolution", sourceComponentId="pay-now", timestamp="t"
        )
        async for _ in server.a2a().send_message(
            SendMessageRequest(
                message=action_message(forged, task_id=task_id, context_id=context_id)
            )
        ):
            pass
        refused: list[InboxAuditRecord] = []
        for _ in range(50):
            audits = await server.harness.store.query(InboxAuditRecord, Filter(task_id=task_id))
            refused = [a for a in audits if not a.accepted]
            if refused:
                break
            await asyncio.sleep(0.05)
        assert refused and refused[0].reason == "a2ui.unknown_surface_or_component"
        genuine = Action(
            name="confirm",
            surfaceId="resolution",
            sourceComponentId="ok",
            timestamp="2026-10-09T12:00:00Z",
            context={"choice": "replace"},
        )
        final = None
        async for event in server.a2a().send_message(
            SendMessageRequest(
                message=action_message(genuine, task_id=task_id, context_id=context_id)
            )
        ):
            if event.HasField("status_update"):
                final = event.status_update.status.state
        assert final == TaskState.TASK_STATE_COMPLETED
    texts = [i.text for i in server.harness.llm.requests[-1].input if i.kind == "message"]
    assert any(
        "[A2UI action] confirm on surface resolution from ok" in t and "replace" in t for t in texts
    )
