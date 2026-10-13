"""Feature: The push endpoint refuses what it cannot verify (issue-27, abuse cases 1-9)
Requirement: docs/specs/issue-27/requirements.md#security-considerations

``POST /a2a/push/{task_id}`` is a new inbound surface. Every refusal is the same ``401``
and changes nothing; a push that is accepted only wakes the stand-in, which takes the
state from its own ``GetTask``; the token is never kept or logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from a2a.types import TaskState
from temporalio.api.enums.v1 import EventType
from temporalio.testing import WorkflowEnvironment

from tests.integration.agents._delegation import Delegation, ask, delegation, parent_script
from tests.integration.durable.conftest import awaiting_next_message, close, env
from tiny_harness.harness.models import scripted
from tiny_harness.harness.persistence import Filter, TaskRecord
from tiny_harness.service.a2a.push import MAX_PUSH_BYTES, PUSH_TOKEN_HEADER
from tiny_harness.service.durable import workflows
from tiny_harness.service.durable.models import PushIn, RemoteWatch

pytestmark = pytest.mark.asyncio(loop_scope="module")
__all__ = ["env"]


def body(remote_id: str, state: str = "TASK_STATE_COMPLETED") -> bytes:
    return json.dumps({"statusUpdate": {"taskId": remote_id, "status": {"state": state}}}).encode()


async def history_length(d: Delegation) -> int:
    """Events that record something: a rejected update may leave an empty workflow task
    (the test server persists it; servers with speculative workflow tasks drop it), but
    never an update, a signal or an activity."""
    handle = d.env.client.get_workflow_handle(d.child_id)
    return len(
        [
            e
            async for e in handle.fetch_history_events()
            if not EventType.Name(e.event_type).startswith("EVENT_TYPE_WORKFLOW_TASK_")
        ]
    )


async def activity_count(d: Delegation, name: str) -> int:
    handle = d.env.client.get_workflow_handle(d.child_id)
    return len(
        [
            e
            async for e in handle.fetch_history_events()
            if e.HasField("activity_task_scheduled_event_attributes")
            and e.activity_task_scheduled_event_attributes.activity_type.name == name
        ]
    )


async def settled_history(d: Delegation) -> int:
    """The history length once the reconciling ``GetTask`` (R1.4) has finished."""
    length = -1
    for _ in range(100):
        await asyncio.sleep(0.2)
        current = await history_length(d)
        if current == length:
            return current
        length = current
    raise AssertionError("the stand-in's history never settled")


async def history_text(d: Delegation) -> str:
    handle = d.env.client.get_workflow_handle(d.child_id)
    return "\n".join([str(e) async for e in handle.fetch_history_events()])


async def parked(env: WorkflowEnvironment) -> AsyncIterator[tuple[Delegation, str, str]]:
    async with delegation(env, parent_script(), [scripted("", tool_calls=[ask()])]) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        config = await d.until_push_config(remote_id)
        # The stand-in starts while the remote works (issue-34 R7.2): hand over once it
        # has heard the remote park, so no relay of its own lands in the test's window.
        await d.until_child(TaskState.TASK_STATE_INPUT_REQUIRED)
        yield d, remote_id, config.token.get_secret_value()
        await d.cancel_remote(remote_id, "test over")
        await d.child()
        await asyncio.sleep(0.3)
        await awaiting_next_message(handle)
        await close(handle)


def local(d: Delegation) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=d.local.app), base_url="http://local"
    )


async def test_unverifiable_pushes_are_refused_alike_and_change_nothing(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Feature: The push endpoint refuses what it cannot verify
    Requirement: docs/specs/issue-27/requirements.md#security-considerations

    Scenario: Missing, wrong and misdirected pushes get one 401 and change nothing (cases 1, 2, 4)
        Given a stand-in watching its parked remote task by push
        When pushes arrive with no token, a wrong token, for an unknown id, for the parent's
            TaskWorkflow, and with the right token naming another remote task
        Then each is answered 401
        And the stand-in's history does not grow and it stays INPUT_REQUIRED
        And the token appears in no log line, no history event and no local store record
    """
    caplog.set_level(logging.DEBUG)
    async for d, remote_id, token in parked(env):
        before = await settled_history(d)
        path = f"/a2a/push/{d.child_id}"
        async with local(d) as http:
            cases: list[tuple[str, dict[str, str], bytes]] = [
                (path, {}, body(remote_id)),
                (path, {PUSH_TOKEN_HEADER: "wrong-" + token[6:]}, body(remote_id)),
                ("/a2a/push/t-nobody.1", {PUSH_TOKEN_HEADER: token}, body(remote_id)),
                (f"/a2a/push/{d.task_id}", {PUSH_TOKEN_HEADER: token}, body(remote_id)),
                (path, {PUSH_TOKEN_HEADER: token}, body("another-remote-task")),
            ]
            for url, headers, payload in cases:
                response = await http.post(url, headers=headers, content=payload)
                assert response.status_code == 401, url
                assert response.content == b""
        assert await history_length(d) == before, "a refused push was recorded"
        assert await d.child_state() == TaskState.TASK_STATE_INPUT_REQUIRED
        assert token not in caplog.text
        assert token not in await history_text(d)
        for record in await d.local.harness.store.query(TaskRecord, Filter()):
            assert token not in record.model_dump_json()


async def test_a_forged_terminal_push_is_not_applied(env: WorkflowEnvironment) -> None:
    """
    Feature: The push endpoint refuses what it cannot verify
    Requirement: docs/specs/issue-27/requirements.md#security-considerations

    Scenario: A push with the right token that claims COMPLETED is only a doorbell (case 6)
        Given a stand-in watching its parked remote task by push
        When a push with the registered token claims the remote task COMPLETED
        Then the endpoint answers 204
        And the stand-in fetches the task, which is still INPUT_REQUIRED, and stays so
        And it fetches again at most three times, since the fetch disagrees with the claim
        And it tells the parent nothing, since nothing changed
    """
    async for d, remote_id, token in parked(env):
        await settled_history(d)
        before = await activity_count(d, "get_remote_task")
        signals = await d.events("SIGNAL_EXTERNAL_WORKFLOW_EXECUTION_INITIATED")
        async with local(d) as http:
            response = await http.post(
                f"/a2a/push/{d.child_id}",
                headers={PUSH_TOKEN_HEADER: token},
                content=body(remote_id, "TASK_STATE_COMPLETED"),
            )
        assert response.status_code == 204
        for _ in range(300):  # every recheck (1 s, 2 s, 4 s) runs
            if await activity_count(d, "get_remote_task") == before + 4:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(1.0)  # and no fifth follows
        assert await activity_count(d, "get_remote_task") == before + 4, "at most four fetches"
        assert await d.child_state() == TaskState.TASK_STATE_INPUT_REQUIRED
        assert await d.events("SIGNAL_EXTERNAL_WORKFLOW_EXECUTION_INITIATED") == signals


async def test_oversized_and_malformed_pushes_are_refused(env: WorkflowEnvironment) -> None:
    """
    Feature: The push endpoint refuses what it cannot verify
    Requirement: docs/specs/issue-27/requirements.md#security-considerations

    Scenario: An oversized or unparseable push is refused before Temporal (abuse case 5)
        Given a stand-in watching its parked remote task by push
        When a push larger than 64 KiB arrives, and one whose body is not a StreamResponse
        Then they are answered 413 and 400, and the stand-in's history does not grow
    """
    async for d, _remote_id, token in parked(env):
        before = await settled_history(d)
        path = f"/a2a/push/{d.child_id}"
        async with local(d) as http:
            big = await http.post(
                path, headers={PUSH_TOKEN_HEADER: token}, content=b"{" + b" " * MAX_PUSH_BYTES
            )
            bad = await http.post(path, headers={PUSH_TOKEN_HEADER: token}, content=b"[1, 2]")
        assert (big.status_code, bad.status_code) == (413, 400)
        assert await history_length(d) == before


async def test_a_push_to_an_ended_stand_in_is_refused(env: WorkflowEnvironment) -> None:
    """
    Feature: The push endpoint refuses what it cannot verify
    Requirement: docs/specs/issue-27/requirements.md#security-considerations

    Scenario: Once a stand-in has ended, its token opens nothing (R5.3, abuse case 2)
        Given a stand-in that registered a push config and then ended CANCELED
        When a push with its old token arrives
        Then the endpoint answers 401
    """
    async with delegation(env, parent_script(), [scripted("", tool_calls=[ask()])]) as d:
        handle = await d.begin()
        remote_id = await d.parked_remote()
        token = (await d.until_push_config(remote_id)).token.get_secret_value()
        await d.cancel_remote(remote_id)
        await d.child()
        async with local(d) as http:
            response = await http.post(
                f"/a2a/push/{d.child_id}",
                headers={PUSH_TOKEN_HEADER: token},
                content=body(remote_id),
            )
        assert response.status_code == 401
        await asyncio.sleep(0.3)
        await awaiting_next_message(handle)
        await close(handle)


def test_the_validator_compares_digests_in_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Abuse case 3: the digest comparison is ``hmac.compare_digest``, never ``==``."""
    calls: list[tuple[bytes, bytes]] = []

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return False

    monkeypatch.setattr(workflows.hmac, "compare_digest", spy)
    stand_in = workflows.RemoteTaskWorkflow()
    stand_in.watch = RemoteWatch(mode="push", config_id="c", token_digest="a" * 64)
    stand_in.remote_task_id = "r-1"
    with pytest.raises(ValueError, match="push not accepted"):
        stand_in._check_push(PushIn(token_digest="b" * 64, remote_task_id="r-1"))  # pyright: ignore[reportPrivateUsage]
    assert calls == [(b"b" * 64, b"a" * 64)]


@pytest.mark.parametrize(
    "watch",
    [None, RemoteWatch(mode="follow"), RemoteWatch(mode="off")],
)
def test_a_stand_in_without_a_push_watch_accepts_no_push(watch: RemoteWatch | None) -> None:
    stand_in = workflows.RemoteTaskWorkflow()
    stand_in.watch = watch
    stand_in.remote_task_id = "r-1"
    with pytest.raises(ValueError, match="push not accepted"):
        stand_in._check_push(PushIn(token_digest="", remote_task_id="r-1"))  # pyright: ignore[reportPrivateUsage]
