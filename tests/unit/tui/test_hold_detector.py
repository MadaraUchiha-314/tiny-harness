"""T1 (issue-38 R3.2, R3.3): hold-to-talk on an empty composer, timed with a fake clock.
A lone Space is typed once its repeat window passes; a second Space inside the window is
auto-repeat and starts a hold; the hold ends when repeats stop for ``release_gap``, or at
once on a key-release event."""

from __future__ import annotations

from tiny_harness.interaction.tui.voice import HoldDetector


def test_a_lone_space_is_typed_after_the_repeat_window() -> None:
    hold = HoldDetector()
    assert hold.key_down(0.0) == "hold" and hold.active
    assert hold.tick(0.5) is None  # still inside the window: held back
    assert hold.tick(0.61) == "type-space"
    assert not hold.active and hold.tick(5.0) is None


def test_auto_repeat_starts_a_hold_and_its_gap_ends_it() -> None:
    hold = HoldDetector()
    assert hold.key_down(0.0) == "hold"
    assert hold.key_down(0.45) == "start"  # the OS repeat delay, inside the window
    for at in (0.48, 0.51, 0.54, 0.57):
        assert hold.tick(at) is None
        assert hold.key_down(at) == "repeat"
    assert hold.tick(0.80) is None  # 0.23 s since the last repeat
    assert hold.tick(0.83) == "end"
    assert not hold.active


def test_a_release_event_ends_the_hold_at_once() -> None:
    hold = HoldDetector()
    hold.key_down(0.0)
    hold.key_down(0.4)
    assert hold.key_up(0.41) == "end"
    assert hold.tick(0.42) is None


def test_a_tap_released_inside_the_window_is_typed_at_once() -> None:
    hold = HoldDetector()
    hold.key_down(0.0)
    assert hold.key_up(0.08) is None
    assert hold.tick(0.09) == "type-space"


def test_a_second_space_after_the_window_is_a_new_press() -> None:
    hold = HoldDetector()
    hold.key_down(0.0)
    assert hold.tick(0.7) == "type-space"
    assert hold.key_down(0.9) == "hold"


def test_hold_ms_sets_the_repeat_window() -> None:
    """``--hold-ms 300``: a terminal with a short repeat delay."""
    hold = HoldDetector(repeat_window=0.3)
    hold.key_down(0.0)
    assert hold.tick(0.31) == "type-space"
    hold.key_down(1.0)
    assert hold.key_down(1.25) == "start"


def test_the_clock_is_injected() -> None:
    now = [10.0]
    hold = HoldDetector(clock=lambda: now[0])
    assert hold.clock() == 10.0
