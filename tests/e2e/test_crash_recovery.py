"""Feature: crash recovery
Requirement: docs/specs/issue-3/requirements.md#R19

The worker is killed with SIGKILL at two points and restarted; the task completes, and
Temporal's history shows every LLM activity scheduled once and completed once (no
duplicated LLM call), while the orders ledger shows the non-idempotent tool at most once.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from a2a.types import TaskState
from temporalio.api.enums.v1 import EventType

from tests.e2e.demo import SECRET_VARIABLES, Demo, Driver, Event
from tiny_harness.config import Settings
from tiny_harness.service.durable.client import connect

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def demo() -> AsyncIterator[Demo]:
    instance = Demo.create("crash")
    try:
        await instance.start_server()
        instance.start_worker()
        yield instance
    finally:
        instance.stop()


@dataclass
class Attempts:
    """Per activity type: how many attempts were scheduled, completed, timed out, failed."""

    scheduled: Counter[str] = field(default_factory=lambda: Counter[str]())
    completed: Counter[str] = field(default_factory=lambda: Counter[str]())
    timed_out: Counter[str] = field(default_factory=lambda: Counter[str]())
    failed: Counter[str] = field(default_factory=lambda: Counter[str]())

    def summary(self) -> dict[str, dict[str, int]]:
        return {
            name: {
                "scheduled": self.scheduled[name],
                "completed": self.completed[name],
                "timed_out": self.timed_out[name],
                "failed": self.failed[name],
            }
            for name in sorted(self.scheduled)
        }


async def attempts(demo: Demo, task_id: str) -> Attempts:
    settings = Settings.load(demo.config, env=demo.env())
    client = await connect(settings.temporal)
    names: dict[int, str] = {}
    result = Attempts()
    async for event in client.get_workflow_handle(task_id).fetch_history_events():
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            name = event.activity_task_scheduled_event_attributes.activity_type.name
            names[event.event_id] = name
            result.scheduled[name] += 1
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            attrs = event.activity_task_completed_event_attributes
            result.completed[names[attrs.scheduled_event_id]] += 1
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT:
            attrs = event.activity_task_timed_out_event_attributes
            result.timed_out[names[attrs.scheduled_event_id]] += 1
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED:
            attrs = event.activity_task_failed_event_attributes
            result.failed[names[attrs.scheduled_event_id]] += 1
    return result


async def wait_for(predicate: Callable[[], bool], *, timeout: float, what: str) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}")


def write_evidence(demo: Demo, name: str, driver: Driver, notes: dict[str, object]) -> None:
    demo.write_evidence(f"{name}-transcript.txt", driver.transcript())
    demo.write_evidence(f"{name}-history.json", json.dumps(notes, indent=2, default=str))


async def test_a_worker_killed_during_an_idempotent_tool_activity_resumes_on_restart(
    demo: Demo,
) -> None:
    """
    Feature: crash recovery
    Requirement: docs/specs/issue-3/requirements.md#R19

    Scenario: a worker killed during an idempotent tool activity resumes on restart
        Given the orders server holds get_order open (the slow marker)
        When the worker is killed with SIGKILL while get_order is running and restarted
        Then the activity times out on its heartbeat, is retried on the new worker
        And every invoke_llm activity was scheduled once and completed once
        And the task completes after the reporter's reply
    """
    marker = demo.plugin_data / "slow-get-order"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    before = len(demo.ledger())
    driver = Driver(demo)
    killed: list[float] = []

    async def kill_during_get_order() -> None:
        await wait_for(
            lambda: any(r["tool"] == "get_order" for r in demo.ledger()[before:]),
            timeout=180,
            what="get_order to start",
        )
        await asyncio.sleep(1)
        killed.append(demo.kill_worker())
        marker.unlink(missing_ok=True)
        await asyncio.sleep(2)
        demo.start_worker()

    chaos = asyncio.create_task(kill_during_get_order())
    try:
        state = await driver.run(on_event=lambda e: print(e.line()), act_on_card=False)
        await chaos
    finally:
        if not chaos.done():
            chaos.cancel()
        marker.unlink(missing_ok=True)
        await driver.close()
    assert driver.task_id is not None
    history = await attempts(demo, driver.task_id)
    ledger = [r["tool"] for r in demo.ledger()[before:]]
    write_evidence(
        demo,
        "kill-during-tool",
        driver,
        {"killed_at": killed, "attempts": history.summary(), "ledger": ledger},
    )
    assert killed and state == TaskState.TASK_STATE_COMPLETED, driver.transcript()
    assert history.scheduled["invoke_llm"] == history.completed["invoke_llm"], history.summary()
    assert history.timed_out["invoke_tool"] + history.failed["invoke_tool"] >= 1, history.summary()
    assert history.completed["invoke_tool"] >= 1
    assert ledger.count("get_order") >= 2  # the idempotent tool was retried
    assert ledger.count("ship_replacement") == 1 and ledger.count("refund") == 0


async def test_a_worker_killed_while_input_is_required_resumes_on_restart(demo: Demo) -> None:
    """
    Feature: crash recovery
    Requirement: docs/specs/issue-3/requirements.md#R19

    Scenario: a worker killed while input is required resumes on restart
        Given a task waiting in INPUT_REQUIRED
        When the worker is killed with SIGKILL and restarted before the reporter replies
        Then the reply is accepted and the task completes
        And every activity was scheduled once and completed once
    """
    before = len(demo.ledger())
    driver = Driver(demo)
    killed: list[float] = []

    def on_event(event: Event) -> None:
        print(event.line())
        if event.state == TaskState.TASK_STATE_INPUT_REQUIRED and not killed:
            killed.append(demo.kill_worker())
            demo.start_worker()

    try:
        state = await driver.run(on_event=on_event, act_on_card=False)
    finally:
        await driver.close()
    assert driver.task_id is not None
    history = await attempts(demo, driver.task_id)
    ledger = [r["tool"] for r in demo.ledger()[before:]]
    write_evidence(
        demo,
        "kill-during-input-required",
        driver,
        {"killed_at": killed, "attempts": history.summary(), "ledger": ledger},
    )
    assert killed and state == TaskState.TASK_STATE_COMPLETED, driver.transcript()
    assert history.scheduled["invoke_llm"] == history.completed["invoke_llm"], history.summary()
    assert history.scheduled["invoke_tool"] == history.completed["invoke_tool"], history.summary()
    assert ledger.count("ship_replacement") == 1 and ledger.count("refund") == 0
    logs = "".join(demo.read_log(f"worker-{n}.log") for n in range(1, demo.workers_started + 1))
    for name in SECRET_VARIABLES:
        value = os.environ.get(name)
        assert not value or value not in logs, f"{name} leaked into a worker log"
