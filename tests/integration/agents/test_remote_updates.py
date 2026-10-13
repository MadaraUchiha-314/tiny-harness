"""Feature: Remote sub-tasks hear remote state changes between turns
Requirement: docs/specs/issue-27/requirements.md

While a delegated remote task is parked, its stand-in watches it: by push when the remote
card advertises it, by following it with SubscribeToTask otherwise.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from a2a.types import Message, Part, Task, TaskState
from a2a.types import Role as A2ARole
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from tests.integration.agents._delegation import Delegation, ask, delegation, parent_script
from tests.integration.durable.conftest import awaiting_next_message, close, env, until
from tiny_harness.harness.agents import RemoteAgent
from tiny_harness.harness.models import FakeLLM, scripted
from tiny_harness.harness.security import Redactor
from tiny_harness.service.a2a.push import PUSH_TOKEN_HEADER
from tiny_harness.service.durable.models import InboxReceipt
from tiny_harness.service.durable.workflows import TaskWorkflow

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]


def heard(llm: FakeLLM, note: str) -> bool:
    return any(
        note in item.text for r in llm.requests for item in r.input if item.kind == "message"
    )


async def until_events(d: Delegation, event_type: str, activity: str) -> None:
    """Until the stand-in has scheduled ``activity`` and the event ``event_type`` follows."""
    for _ in range(200):
        if await d.events("ACTIVITY_TASK_SCHEDULED", activity) and await d.events(event_type):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{activity} never reached {event_type}")


async def until_heard(llm: FakeLLM, note: str) -> None:
    for _ in range(400):
        if heard(llm, note):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"the parent's model never heard {note!r}")


async def finish(handle: WorkflowHandle[TaskWorkflow, Task], llm: FakeLLM, note: str) -> None:
    """Let the parent take the note and park, then close it (a cancel mid-turn fails it)."""
    await until_heard(llm, note)
    await awaiting_next_message(handle)
    await close(handle)


async def test_a_third_party_cancel_is_heard_through_push(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R2

    Scenario: A third party cancels a parked remote sub-task and the parent hears of it through push
        Given a remote agent whose card advertises push notifications
        And a delegated sub-task the remote agent parked awaiting an answer
        When the stand-in registers a push config pointing at this server
        And a third party cancels the remote task on the remote side
        Then the remote agent's push reaches the endpoint with the registered token
        And the stand-in fetches the task and ends CANCELED
        And the parent's row shows CANCELED and its model is told
        And no message was sent to the remote task after its first turn
        And the push config is deleted from the remote task
    """
    async with delegation(env, parent_script(), [scripted("", tool_calls=[ask()])]) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        config = await d.until_push_config(remote_id)
        assert config.url == f"http://local/a2a/push/{d.child_id}"
        await d.cancel_remote(remote_id)
        child = await d.child()
        assert child.status.state == TaskState.TASK_STATE_CANCELED
        await until_heard(d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")
        parked = await until(
            handle, lambda t: bool(t.ext.sub_tasks) and t.ext.sub_tasks[0].state == "CANCELED"
        )
        assert parked.ext.sub_tasks[0].task_id == d.child_id
        assert len(d.remote.harness.llm.requests) == 1, "nothing was sent to the remote again"
        assert await d.push_configs(remote_id) == []
        assert any(p.url.path == f"/a2a/push/{d.child_id}" for p in d.remote.pushes)
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_without_push_the_stand_in_follows_and_hears_a_completion(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R3

    Scenario: Without push the stand-in follows the parked task and hears a third-party completion
        Given a remote agent configured with updates = "follow"
        And a delegated sub-task the remote agent parked awaiting an answer
        When a third party completes the remote task on the remote side
        Then the stand-in hears it on its SubscribeToTask stream and ends COMPLETED
        And the parent's model is told, with the remote's closing words
        And no push config was ever registered
    """
    async with delegation(
        env, parent_script(), [scripted("", tool_calls=[ask()])], updates="follow"
    ) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_child(TaskState.TASK_STATE_INPUT_REQUIRED)
        await d.complete_remote(remote_id)
        child = await d.child()
        assert child.status.state == TaskState.TASK_STATE_COMPLETED
        await until_heard(d.local.harness.llm, f"Sub-task {d.child_id} is COMPLETED")
        assert len(d.remote.harness.llm.requests) == 1
        assert await d.push_configs(remote_id) == []
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is COMPLETED")


async def test_a_card_without_push_is_followed(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R4

    Scenario: updates = "auto" follows a remote agent whose card advertises no push
        Given a remote agent whose card does not advertise push notifications
        When its parked task is cancelled by a third party
        Then the stand-in hears it by following and ends CANCELED, with no push config
    """

    def no_push(agent: RemoteAgent) -> None:
        agent.agent_card.capabilities.push_notifications = False

    async with delegation(
        env, parent_script(), [scripted("", tool_calls=[ask()])], configure=no_push
    ) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_child(TaskState.TASK_STATE_INPUT_REQUIRED)
        await d.cancel_remote(remote_id)
        assert (await d.child()).status.state == TaskState.TASK_STATE_CANCELED
        assert await d.push_configs(remote_id) == []
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_a_reply_while_following_cancels_the_follow(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R3

    Scenario: A reply while following cancels the follow and starts a turn
        Given a stand-in following a parked remote task
        When a reply from a local participant the remote does not know reaches the inbox
        Then the follow is cancelled and the reply is sent to the remote task
        And the remote answers and the stand-in completes
    """
    remote = [scripted("", tool_calls=[ask()]), scripted("Ledger is balanced.")]
    async with delegation(env, parent_script(), remote, updates="follow") as d:
        handle = await d.begin()
        await d.parked_remote()
        await d.until_child(TaskState.TASK_STATE_INPUT_REQUIRED)
        await until_events(d, "ACTIVITY_TASK_STARTED", "follow_remote_task")
        stand_in = d.env.client.get_workflow_handle(d.child_id)
        # From a participant the remote task does not know: the stand-in asserts itself.
        reply = message_to(d.child_id, "The main ledger.", participant="alice")
        await stand_in.execute_update(  # pyright: ignore[reportUnknownMemberType]
            "inbox", reply, result_type=InboxReceipt
        )
        child = await d.child()
        assert child.status.state == TaskState.TASK_STATE_COMPLETED
        assert len(d.remote.harness.llm.requests) == 2
        assert await d.events("ACTIVITY_TASK_CANCEL_REQUESTED") >= 1, "the follow was cancelled"
        await until_heard(d.local.harness.llm, "Ledger is balanced.")
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is COMPLETED")


async def test_updates_off_keeps_todays_behaviour(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R4

    Scenario: updates = "off" keeps today's behaviour
        Given a remote agent configured with updates = "off"
        When its parked task is cancelled by a third party
        Then the stand-in stays INPUT_REQUIRED and registers no push config
    """
    async with delegation(
        env, parent_script(), [scripted("", tool_calls=[ask()])], updates="off"
    ) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_child(TaskState.TASK_STATE_INPUT_REQUIRED)
        await d.cancel_remote(remote_id)
        await asyncio.sleep(1.0)
        assert await d.child_state() == TaskState.TASK_STATE_INPUT_REQUIRED
        assert await d.push_configs(remote_id) == []
        await d.env.client.get_workflow_handle(d.child_id).signal("cancel", "test over")
        await d.child()
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_the_push_config_is_deleted_when_the_stand_in_is_cancelled(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R5

    Scenario: The push config is deleted when the stand-in is cancelled
        Given a stand-in that registered a push config on its parked remote task
        When the stand-in is cancelled
        Then it ends CANCELED and the push config is gone from the remote task
        And the remote task itself is left as it was
    """
    async with delegation(env, parent_script(), [scripted("", tool_calls=[ask()])]) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_push_config(remote_id)
        await d.env.client.get_workflow_handle(d.child_id).signal("cancel", "parent cancelled")
        assert (await d.child()).status.state == TaskState.TASK_STATE_CANCELED
        assert await d.push_configs(remote_id) == []
        remote_task = await d.env.client.get_workflow_handle(remote_id).query(
            "task", result_type=Task
        )
        assert remote_task.status.state == TaskState.TASK_STATE_INPUT_REQUIRED
        await d.cancel_remote(remote_id, "test over")
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_a_failed_registration_falls_back_to_follow(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R1

    Scenario: A failed registration falls back to follow
        Given a remote agent that advertises push but fails SetTaskPushNotificationConfig
        When its parked task is cancelled by a third party
        Then the stand-in hears it by following and ends CANCELED
    """

    def broken_push(agent: RemoteAgent) -> None:
        async def refuse(*args: object, **kwargs: object) -> str:
            raise RuntimeError("push configs are disabled here")

        agent.set_push_config = refuse  # type: ignore[method-assign]

    async with delegation(
        env, parent_script(), [scripted("", tool_calls=[ask()])], configure=broken_push
    ) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_child(TaskState.TASK_STATE_INPUT_REQUIRED)
        await asyncio.sleep(0.3)
        await d.cancel_remote(remote_id)
        assert (await d.child()).status.state == TaskState.TASK_STATE_CANCELED
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_a_remote_resumed_by_a_third_party_wakes_the_model_only_at_its_end(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R2

    Scenario: The parent's row moves and its model is told only of an ending or a new question
        Given a stand-in watching its parked remote task by push
        When a third party answers the remote task directly, so it resumes and finishes
        Then the stand-in ends COMPLETED with the remote's answer
        And the parent's model is told of the completion but never of WORKING
    """
    remote = [scripted("", tool_calls=[ask()]), scripted("Ledger is balanced.")]
    async with delegation(env, parent_script(), remote) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_push_config(remote_id)
        await d.env.client.get_workflow_handle(remote_id).execute_update(  # pyright: ignore[reportUnknownMemberType]
            "inbox", message_to(remote_id, "The main ledger."), result_type=InboxReceipt
        )
        child = await d.child()
        assert child.status.state == TaskState.TASK_STATE_COMPLETED
        await until_heard(d.local.harness.llm, f"Sub-task {d.child_id} is COMPLETED")
        assert not heard(d.local.harness.llm, "is WORKING")
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is COMPLETED")


def message_to(task_id: str, text: str, *, participant: str = "tiny-harness") -> Message:
    msg = Message(
        message_id=uuid.uuid4().hex,
        task_id=task_id,
        role=A2ARole.ROLE_USER,
        parts=[Part(text=text)],
    )
    msg.metadata.update({"participant_id": participant})
    return msg


async def test_a_redacted_status_text_does_not_spin_the_follow(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R3

    Scenario: A status text the redactor masks is compared as it is recorded
        Given a stand-in following a parked remote task whose question holds a secret
        When the follow reads the task's current state from its stream
        Then it sees no change, because it compares the scrubbed text
        And the stand-in does not start follow after follow
    """
    async with delegation(
        env,
        parent_script(),
        [scripted("", tool_calls=[ask("Ledger 77-secret-77?")])],
        updates="follow",
    ) as d:
        d.local.harness.engine.runner._redactor = Redactor(["77-secret-77"])  # pyright: ignore[reportPrivateUsage]
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_child(TaskState.TASK_STATE_INPUT_REQUIRED)
        await until_events(d, "ACTIVITY_TASK_STARTED", "follow_remote_task")
        completed = await d.events("ACTIVITY_TASK_COMPLETED")
        await asyncio.sleep(1.5)
        # The first follow is still open: it saw no "change" in the masked question.
        assert await d.events("ACTIVITY_TASK_COMPLETED") == completed
        assert await d.events("ACTIVITY_TASK_SCHEDULED", "follow_remote_task") == 1
        await d.cancel_remote(remote_id)
        assert (await d.child()).status.state == TaskState.TASK_STATE_CANCELED
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_a_failed_cleanup_still_ends_in_the_state_reached(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R5

    Scenario: A push config that cannot be deleted does not change how the stand-in ends
        Given a stand-in watching by push whose agent fails DeleteTaskPushNotificationConfig
        When a third party cancels the remote task
        Then the stand-in still ends CANCELED and the parent hears of it
    """

    def broken_delete(agent: RemoteAgent) -> None:
        async def refuse(*args: object, **kwargs: object) -> None:
            raise RuntimeError("cannot delete")

        agent.delete_push_config = refuse  # type: ignore[method-assign]

    async with delegation(
        env, parent_script(), [scripted("", tool_calls=[ask()])], configure=broken_delete
    ) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_push_config(remote_id)
        await d.cancel_remote(remote_id)
        assert (await d.child()).status.state == TaskState.TASK_STATE_CANCELED
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_a_long_parked_stand_in_continues_as_new(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R2

    Scenario: A stand-in whose history passes the bound rolls over and keeps watching
        Given a stand-in watching by push, with a small history bound
        When pushes grow its history past the bound
        Then it continues as new, still parked, with its push watch
        And a third-party cancel afterwards is still heard
    """
    async with delegation(env, parent_script(), [scripted("", tool_calls=[ask()])]) as d:
        handle = await d.begin(history_event_bound=60)
        remote_id = await d.parked_remote()
        token = (await d.until_push_config(remote_id)).token.get_secret_value()
        http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=d.local.app), base_url="http://local"
        )
        body = json.dumps(
            {
                "statusUpdate": {
                    "taskId": remote_id,
                    "status": {"state": "TASK_STATE_INPUT_REQUIRED"},
                }
            }
        ).encode()
        for _ in range(60):
            if await d.continued():
                break
            await http.post(
                f"/a2a/push/{d.child_id}", headers={PUSH_TOKEN_HEADER: token}, content=body
            )
            await asyncio.sleep(0.1)
        await http.aclose()
        assert await d.continued(), "the stand-in never rolled over"
        assert await d.child_state() == TaskState.TASK_STATE_INPUT_REQUIRED
        await d.cancel_remote(remote_id)
        assert (await d.child()).status.state == TaskState.TASK_STATE_CANCELED
        assert await d.push_configs(remote_id) == []
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_a_fetch_failing_on_the_last_recheck_leaves_the_stand_in_working(
    env: WorkflowEnvironment,
) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R2

    Scenario: A failed fetch during the rechecks keeps the last state and the watch alive
        Given a stand-in watching by push
        When a push claims a state the remote does not show, and the last recheck's fetch fails
        Then the stand-in keeps its last state
        And a third-party cancel afterwards is still heard
    """
    calls = 0

    def flaky(agent: RemoteAgent) -> None:
        real = agent.get_task

        async def get_task(task_id: str, *, participant: str | None = None) -> Task:
            nonlocal calls
            calls += 1
            if calls == 5:  # the reconcile, the push's fetch, rechecks 1, 2 — then 3 fails
                raise RuntimeError("remote unavailable")
            return await real(task_id, participant=participant)

        agent.get_task = get_task  # type: ignore[method-assign]

    async with delegation(
        env, parent_script(), [scripted("", tool_calls=[ask()])], configure=flaky
    ) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        token = (await d.until_push_config(remote_id)).token.get_secret_value()
        for _ in range(100):
            if calls >= 1:
                break
            await asyncio.sleep(0.05)
        claim = {"state": "TASK_STATE_COMPLETED"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=d.local.app), base_url="http://local"
        ) as http:
            response = await http.post(
                f"/a2a/push/{d.child_id}",
                headers={PUSH_TOKEN_HEADER: token},
                content=json.dumps({"statusUpdate": {"taskId": remote_id, "status": claim}}),
            )
        assert response.status_code == 204
        for _ in range(300):
            if calls >= 5:
                break
            await asyncio.sleep(0.05)
        assert calls >= 5, "the rechecks never reached the failing fetch"
        await asyncio.sleep(0.5)
        assert await d.child_state() == TaskState.TASK_STATE_INPUT_REQUIRED
        await d.cancel_remote(remote_id)
        assert (await d.child()).status.state == TaskState.TASK_STATE_CANCELED
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")


async def test_pushes_during_a_turn_are_applied_after_it(env: WorkflowEnvironment) -> None:
    """
    Feature: Remote sub-tasks hear remote state changes between turns
    Requirement: docs/specs/issue-27/requirements.md#R2

    Scenario: A push that arrives while a turn's stream is open is applied only after the turn
        Given a stand-in watching by push whose remote asks a second question after a reply
        When the reply's turn runs, and the remote pushes its WORKING and INPUT_REQUIRED events
        Then the turn's own result is what the parent hears, and the second question is noted
        And the pushes cost one fetch after the turn and no rechecks
    """
    remote = [scripted("", tool_calls=[ask()]), scripted("", tool_calls=[ask("And the year?")])]
    async with delegation(env, [*parent_script(), scripted("Done.")], remote) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        await d.until_push_config(remote_id)
        await asyncio.sleep(0.5)  # the reconcile fetch has run
        before = await d.events("ACTIVITY_TASK_SCHEDULED", "get_remote_task")
        stand_in = d.env.client.get_workflow_handle(d.child_id)
        await stand_in.execute_update(  # pyright: ignore[reportUnknownMemberType]
            "inbox", message_to(d.child_id, "The main ledger."), result_type=InboxReceipt
        )
        await until_heard(d.local.harness.llm, "And the year?")
        await asyncio.sleep(4.0)  # long enough for rechecks at 1 s and 3 s, were any due
        assert await d.events("ACTIVITY_TASK_SCHEDULED", "get_remote_task") <= before + 1
        assert not heard(d.local.harness.llm, "is WORKING")
        await d.cancel_remote(remote_id)
        assert (await d.child()).status.state == TaskState.TASK_STATE_CANCELED
        await finish(handle, d.local.harness.llm, f"Sub-task {d.child_id} is CANCELED")
