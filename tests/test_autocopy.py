"""The click-run counter behind double-click and triple-click selection.

A low-level mouse hook never sees WM_LBUTTONDBLCLK, so `_ClickRun` reimplements
the rule Windows applies further up the stack: a press continues a run when it
lands inside the double-click interval and inside the double-click rectangle of
the press before it. It is pure state with no Win32 and no Qt in it, which is
the whole reason it can be tested at all.

Everything else in autocopy.py is a hook callback or a Win32 call, and is not
reachable from a test.
"""

from __future__ import annotations

import pytest

from autocopy import BLOCKED_PROCESSES, CLICK_KINDS, MAX_CLICKS, _ClickRun


@pytest.fixture
def run():
    """A 500 ms interval and a 2 px rectangle, matching a default mouse."""
    return _ClickRun(interval_ms=500, slop=(2, 2))


# -- counting --------------------------------------------------------------
def test_first_press_is_click_one(run):
    assert run.press(1000, 50, 50) == 1


def test_a_second_press_in_time_and_place_is_a_double_click(run):
    run.press(1000, 50, 50)
    assert run.press(1200, 50, 50) == 2


def test_a_third_press_is_a_triple_click(run):
    run.press(1000, 50, 50)
    run.press(1200, 50, 50)
    assert run.press(1400, 50, 50) == 3


def test_a_run_keeps_counting_past_three(run):
    """Counting is honest; MAX_CLICKS is what decides to stop acting on it."""
    for expected in range(1, 6):
        assert run.press(1000 + 100 * expected, 50, 50) == expected


# -- what breaks a run -----------------------------------------------------
def test_a_slow_second_press_starts_a_new_run(run):
    run.press(1000, 50, 50)
    assert run.press(1501, 50, 50) == 1


def test_a_press_exactly_on_the_interval_still_counts(run):
    run.press(1000, 50, 50)
    assert run.press(1500, 50, 50) == 2


@pytest.mark.parametrize("dx,dy", [(3, 0), (0, 3), (3, 3), (-3, 0), (0, -3)])
def test_a_press_outside_the_rectangle_starts_a_new_run(run, dx, dy):
    run.press(1000, 50, 50)
    assert run.press(1100, 50 + dx, 50 + dy) == 1


@pytest.mark.parametrize("dx,dy", [(2, 0), (0, 2), (2, 2), (-2, -2), (1, -1)])
def test_a_press_on_the_edge_of_the_rectangle_counts(run, dx, dy):
    run.press(1000, 50, 50)
    assert run.press(1100, 50 + dx, 50 + dy) == 2


def test_drift_is_measured_against_the_previous_press_not_the_first(run):
    """Windows compares each press with the one before it, so slow drift adds up."""
    run.press(1000, 50, 50)
    assert run.press(1100, 52, 50) == 2
    assert run.press(1200, 54, 50) == 3


def test_a_backwards_timestamp_starts_a_new_run(run):
    """The hook's timestamp is a 32-bit tick count and wraps every ~49 days."""
    run.press(4_294_967_200, 50, 50)
    assert run.press(40, 50, 50) == 1


def test_reset_ends_the_run(run):
    run.press(1000, 50, 50)
    run.reset()
    assert run.press(1100, 50, 50) == 1
    assert run.count == 1


def test_count_reports_the_last_press(run):
    assert run.count == 0
    run.press(1000, 50, 50)
    run.press(1100, 50, 50)
    assert run.count == 2


# -- the metrics it is built from ------------------------------------------
def test_a_zero_interval_never_pairs_two_presses():
    """A machine reporting nonsense should miss double-clicks, not invent them."""
    run = _ClickRun(interval_ms=0, slop=(2, 2))
    run.press(1000, 50, 50)
    assert run.press(1001, 50, 50) == 1


def test_a_generous_interval_pairs_a_slow_second_press():
    run = _ClickRun(interval_ms=900, slop=(2, 2))
    run.press(1000, 50, 50)
    assert run.press(1850, 50, 50) == 2


# -- the guards ------------------------------------------------------------
def test_click_kinds_cover_every_count_that_fires():
    """Every count between 2 and MAX_CLICKS has a name for the status line."""
    assert set(CLICK_KINDS) == set(range(2, MAX_CLICKS + 1))


def test_blocked_processes_are_lowercase_with_an_extension():
    """They are compared against os.path.basename(...).lower(), so they must match it."""
    for name in BLOCKED_PROCESSES:
        assert name == name.lower()
        assert name.endswith(".exe")


def test_the_usual_password_managers_are_blocked():
    for name in ("keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe"):
        assert name in BLOCKED_PROCESSES
