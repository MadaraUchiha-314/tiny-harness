"""One heartbeat schedule per agent (issue-36 R5.6, R7): the default agent keeps
``tiny-harness-heartbeat``; every other agent gets its own."""

from __future__ import annotations

from tiny_harness.service.heartbeat import SCHEDULE_ID, schedule_id


def test_the_default_agent_keeps_its_schedule() -> None:
    assert schedule_id() == schedule_id("tiny-harness") == SCHEDULE_ID == "tiny-harness-heartbeat"


def test_each_agent_has_its_own_schedule() -> None:
    names = {schedule_id(agent) for agent in ("a", "b", "c", "tiny-harness")}
    assert names == {
        "tiny-harness-heartbeat-a",
        "tiny-harness-heartbeat-b",
        "tiny-harness-heartbeat-c",
        "tiny-harness-heartbeat",
    }
