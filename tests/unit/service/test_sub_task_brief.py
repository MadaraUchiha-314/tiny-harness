"""What a delegated sub-task is told, and what comes back to its parent (issue-34 R7)."""

from __future__ import annotations

from tiny_harness.service.durable.workflows import (
    SUB_TASK_RESULT_CAP,
    sub_task_brief,
    sub_task_result,
)


def test_the_brief_is_the_goal_alone_when_nothing_else_is_given() -> None:
    assert sub_task_brief("Check order 48213", "", ()) == "Check order 48213"


def test_the_brief_carries_the_description_and_each_criterion() -> None:
    brief = sub_task_brief(
        "Check order 48213", "The customer is alice.", ("Names the carrier", "Gives a date")
    )
    assert brief == (
        "Check order 48213\n\nThe customer is alice.\n\n"
        "Acceptance criteria:\n- Names the carrier\n- Gives a date"
    )


def test_a_result_within_the_cap_comes_back_whole() -> None:
    text = "r" * SUB_TASK_RESULT_CAP
    assert sub_task_result(text) == text


def test_a_longer_result_is_cut_and_marked() -> None:
    out = sub_task_result("r" * (SUB_TASK_RESULT_CAP + 50))
    assert len(out) == SUB_TASK_RESULT_CAP and out.endswith("…")


def test_the_cap_holds_a_useful_result() -> None:
    assert SUB_TASK_RESULT_CAP >= 4_000  # was 500: too small to return a result in
